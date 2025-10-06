import dataclasses
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

TableName = str
PropertySourceColumnName = str
PropertyGroupName = str


@dataclass
class PropertyGroupDefinition:
    key_filter_expression: str
    key_filter_function: Callable[[str], bool]
    codec: str = "ZSTD(1)"
    is_materialized: bool = True
    column_type_name: str = "map"
    hidden: bool = (
        False  # whether or not this column should be returned when searching for groups containing a property key
    )

    def contains(self, property_key: str) -> bool:
        if self.hidden:
            return False
        else:
            return self.key_filter_function(property_key)

    def get_column_name(self, source_column: PropertySourceColumnName, group_name: PropertyGroupName) -> str:
        return f"{source_column}_{self.column_type_name}_{group_name}"

    def get_column_definition(self, source_column: PropertySourceColumnName, group_name: PropertyGroupName) -> str:
        column_definition = f"{self.get_column_name(source_column, group_name)} Map(String, String)"
        if not self.is_materialized:
            return column_definition

        return f"""\
            {column_definition}
            MATERIALIZED mapSort(
                mapFilter((key, _) -> {self.key_filter_expression},
                CAST(JSONExtractKeysAndValues({source_column}, 'String'), 'Map(String, String)'))
            )
            CODEC({self.codec})
        """

    def get_index_definitions(
        self, source_column: PropertySourceColumnName, group_name: PropertyGroupName
    ) -> Iterable[str]:
        if not self.is_materialized:
            return

        map_column_name = self.get_column_name(source_column, group_name)
        yield f"{map_column_name}_keys_bf mapKeys({map_column_name}) TYPE bloom_filter"
        yield f"{map_column_name}_values_bf mapValues({map_column_name}) TYPE bloom_filter"


class PropertyGroupManager:
    def __init__(
        self,
        groups: Mapping[
            TableName, Mapping[PropertySourceColumnName, Mapping[PropertyGroupName, PropertyGroupDefinition]]
        ],
    ) -> None:
        self.__groups = groups

    def get_property_group_columns(
        self, table: TableName, source_column: PropertySourceColumnName, property_key: str
    ) -> Iterable[str]:
        """
        Returns an iterable of column names for the map columns responsible for the provided property key and source
        column. The iterable may contain zero items if no maps contain the property key, or multiple items if more than
        one map if the keyspaces of the defined groups for that source column are overlapping.
        """
        if (table_groups := self.__groups.get(table)) and (column_groups := table_groups.get(source_column)):
            for group_name, group_definition in column_groups.items():
                if group_definition.contains(property_key):
                    yield group_definition.get_column_name(source_column, group_name)

    def get_create_table_pieces(self, table: TableName) -> Iterable[str]:
        """
        Returns an iterable of SQL DDL chunks that can be used to define all property groups for the provided table as
        part of a CREATE TABLE statement.
        """
        for source_column, groups in self.__groups[table].items():
            for group_name, group_definition in groups.items():
                yield group_definition.get_column_definition(source_column, group_name)
                for index_definition in group_definition.get_index_definitions(source_column, group_name):
                    yield f"INDEX {index_definition}"

    def get_alter_create_statements(
        self,
        table: TableName,
        source_column: PropertySourceColumnName,
        group_name: PropertyGroupName,
        cluster: str | None = None,
    ) -> Iterable[str]:
        """
        Returns an iterable of ALTER TABLE statements that can be used to create the property group (e.g. as part of a
        migration) if it doesn't already exist.
        """
        prefix = f"ALTER TABLE {table}"
        if cluster is not None:
            prefix += f" ON CLUSTER {cluster}"

        group_definition = self.__groups[table][source_column][group_name]

        commands = [f"ADD COLUMN IF NOT EXISTS {group_definition.get_column_definition(source_column, group_name)}"]
        for index_definition in group_definition.get_index_definitions(source_column, group_name):
            commands.append(f"ADD INDEX IF NOT EXISTS {index_definition}")

        yield f"{prefix} " + ", ".join(commands)

    def get_alter_modify_statements(
        self,
        table: TableName,
        source_column: PropertySourceColumnName,
        group_name: PropertyGroupName,
        cluster: str | None = None,
    ) -> Iterable[str]:
        """
        Returns an iterable of ALTER TABLE statements that can be used to modify the property group
        using MODIFY COLUMN statements.
        **Note** this does not modify the materialized data on disk for the column. This means that
        you should only be using this for removing items out of the map, or be prepared to immediately
        re-materialize the data and have some inconsistent/missing results in the meantime.
        """
        prefix = f"ALTER TABLE {table}"
        if cluster is not None:
            prefix += f" ON CLUSTER {cluster}"

        group_definition = self.__groups[table][source_column][group_name]

        commands = [f"MODIFY COLUMN {group_definition.get_column_definition(source_column, group_name)}"]
        for index_definition in group_definition.get_index_definitions(source_column, group_name):
            commands.append(f"ADD INDEX IF NOT EXISTS {index_definition}")

        yield f"{prefix} " + ", ".join(commands)


ignore_custom_properties = [
    # `token` & `distinct_id` properties are sent with ~50% of events and by
    # many teams, and should not be treated as custom properties and their use
    # should be optimized separately
    "token",
    "distinct_id",
    # campaign properties are defined by external entities and are commonly used
    # across a large number of teams, and should also be optimized separately
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "gclid",  # google ads
    "gad_source",  # google ads
    "gclsrc",  # google ads 360
    "dclid",  # google display ads
    "gbraid",  # google ads, web to app
    "wbraid",  # google ads, app to web
    "fbclid",  # facebook
    "msclkid",  # microsoft
    "twclid",  # twitter
    "li_fat_id",  # linkedin
    "mc_cid",  # mailchimp campaign id
    "igshid",  # instagram
    "ttclid",  # tiktok
    "rdt_cid",  # reddit
    "epik",  # pinterest
    "qclid",  # quora
    "sccid",  # snapchat
    "irclid",  # impact
    "_kx",  # klaviyo
]

event_property_group_definitions = {
    "properties": {
        "custom": PropertyGroupDefinition(
            f"key NOT LIKE '$%' AND key NOT IN (" + f", ".join(f"'{name}'" for name in ignore_custom_properties) + f")",
            lambda key: not key.startswith("$") and key not in ignore_custom_properties,
            column_type_name="group",
        ),
        "ai": PropertyGroupDefinition(
            "key LIKE '$ai_%' AND key != '$ai_input' AND key != '$ai_output_choices'",
            lambda key: key.startswith("$ai_") and key != "$ai_input" and key != "$ai_output_choices",
            column_type_name="group",
        ),
        "feature_flags": PropertyGroupDefinition(
            "key like '$feature/%'",
            lambda key: key.startswith("$feature/"),
            column_type_name="group",
        ),
    },
    "person_properties": {
        "custom": PropertyGroupDefinition(
            f"key NOT LIKE '$%'",
            lambda key: not key.startswith("$"),
        ),
    },
}

property_groups = PropertyGroupManager(
    {
        "sharded_events": event_property_group_definitions,
        "events": {
            # the events distributed table shares the same property group names and types as the sharded_events table,
            # just without the materialize statements
            column_name: {
                group_name: dataclasses.replace(group_definition, is_materialized=False)
                for group_name, group_definition in column_group_definitions.items()
            }
            for column_name, column_group_definitions in event_property_group_definitions.items()
        },
        "logs": {
            "attributes": {
                "str": PropertyGroupDefinition(
                    "key like '%__str'",
                    lambda key: key.endswith("__str"),
                    column_type_name="map",
                    is_materialized=False,
                ),
                "float": PropertyGroupDefinition(
                    "key like '%__float'",
                    lambda key: key.endswith("__float"),
                    column_type_name="map",
                    is_materialized=False,
                ),
                "datetime": PropertyGroupDefinition(
                    "key like '%__datetime'",
                    lambda key: key.endswith("__datetime"),
                    column_type_name="map",
                    is_materialized=False,
                ),
            }
        },
    }
)
