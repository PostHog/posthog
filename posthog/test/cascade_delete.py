import functools

from django.db import connections, router
from django.db.models import Model, QuerySet
from django.db.models.deletion import Collector, get_candidate_relations_to_delete

from psycopg import sql


@functools.cache
def _referencing_tables(model: type[Model]) -> frozenset[str]:
    return frozenset(
        relation.related_model._meta.db_table
        for relation in get_candidate_relations_to_delete(model._meta)
        if relation.related_model is not None
    )


def _empty_tables(using: str, tables: frozenset[str]) -> frozenset[str]:
    with connections[using].cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, pg_relation_size(c.oid) > 0
            FROM pg_class c
            WHERE c.relname = ANY(%s)
              AND c.relkind = 'r'
              AND pg_table_is_visible(c.oid)
            """,
            [sorted(tables)],
        )
        rows = cursor.fetchall()
        empty = {name for name, has_pages in rows if not has_pages}
        tables_with_pages = [name for name, has_pages in rows if has_pages]
        if tables_with_pages:
            probe = sql.SQL(" UNION ALL ").join(
                sql.SQL("SELECT {}, NOT EXISTS (SELECT FROM {})").format(sql.Literal(name), sql.Identifier(name))
                for name in tables_with_pages
            )
            cursor.execute(probe.as_string(cursor.connection))
            empty.update(name for name, is_empty in cursor.fetchall() if is_empty)
    return frozenset(empty)


class _EmptyTableSkippingCollector(Collector):
    def __init__(self, using: str, origin: Model) -> None:
        super().__init__(using=using, origin=origin)
        self._empty_referencing_tables: dict[type[Model], frozenset[str]] = {}

    def related_objects(self, related_model, related_fields, objs) -> QuerySet:
        referenced_model = related_fields[0].remote_field.model
        if referenced_model not in self._empty_referencing_tables:
            self._empty_referencing_tables[referenced_model] = _empty_tables(
                self.using, _referencing_tables(referenced_model)
            )
        if related_model._meta.db_table in self._empty_referencing_tables[referenced_model]:
            return related_model._base_manager.using(self.using).none()
        return super().related_objects(related_model, related_fields, objs)


def delete_skipping_empty_tables(instance: Model) -> tuple[int, dict[str, int]]:
    using = router.db_for_write(type(instance), instance=instance)
    collector = _EmptyTableSkippingCollector(using=using, origin=instance)
    collector.collect([instance])
    return collector.delete()
