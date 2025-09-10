from posthog.clickhouse.property_groups import property_groups


class TestSystemPropertyGroup:
    def test_system_property_group_definition_exists(self):
        """Test that the system property group is defined for events tables"""
        # Check sharded_events table has system property group
        assert "system" in property_groups._PropertyGroupManager__groups["sharded_events"]["properties"]

        # Check events table has system property group
        assert "system" in property_groups._PropertyGroupManager__groups["events"]["properties"]

    def test_system_property_group_matches_dollar_properties(self):
        """Test that the system property group correctly identifies $ properties"""
        system_group = property_groups._PropertyGroupManager__groups["sharded_events"]["properties"]["system"]

        # Should match properties starting with $
        assert system_group.contains("$browser")
        assert system_group.contains("$browser_version")
        assert system_group.contains("$os")
        assert system_group.contains("$device_type")
        assert system_group.contains("$current_url")
        assert system_group.contains("$host")
        assert system_group.contains("$pathname")
        assert system_group.contains("$screen_height")
        assert system_group.contains("$screen_width")
        assert system_group.contains("$lib")
        assert system_group.contains("$lib_version")
        assert system_group.contains("$insert_id")
        assert system_group.contains("$time")
        assert system_group.contains("$device_id")
        assert system_group.contains("$user_id")
        assert system_group.contains("$ip")

        # Should not match properties not starting with $
        assert not system_group.contains("browser")
        assert not system_group.contains("custom_property")
        assert not system_group.contains("utm_source")
        assert not system_group.contains("token")

    def test_system_property_group_column_name(self):
        """Test that the system property group generates the correct column name"""
        system_group = property_groups._PropertyGroupManager__groups["sharded_events"]["properties"]["system"]

        column_name = system_group.get_column_name("properties", "system")
        assert column_name == "properties_group_system"

    def test_system_property_group_overlaps_with_ai_and_feature_flags(self):
        """Test that system property group includes AI and feature flag properties"""
        system_group = property_groups._PropertyGroupManager__groups["sharded_events"]["properties"]["system"]
        ai_group = property_groups._PropertyGroupManager__groups["sharded_events"]["properties"]["ai"]
        feature_flags_group = property_groups._PropertyGroupManager__groups["sharded_events"]["properties"][
            "feature_flags"
        ]

        # System group should include AI properties (they start with $)
        assert system_group.contains("$ai_language")
        assert ai_group.contains("$ai_language")

        # System group should include feature flag properties (they start with $)
        assert system_group.contains("$feature/my-flag")
        assert feature_flags_group.contains("$feature/my-flag")

        # But system group has broader coverage
        assert system_group.contains("$browser")
        assert not ai_group.contains("$browser")
        assert not feature_flags_group.contains("$browser")

    def test_get_property_group_columns_returns_system_for_dollar_properties(self):
        """Test that get_property_group_columns returns system column for $ properties"""
        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$browser"))
        assert "properties_group_system" in columns

        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$device_type"))
        assert "properties_group_system" in columns

        # AI properties should return both AI and system columns
        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$ai_language"))
        assert "properties_group_ai" in columns
        assert "properties_group_system" in columns

        # Feature flag properties should return both feature_flags and system columns
        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$feature/test"))
        assert "properties_group_feature_flags" in columns
        assert "properties_group_system" in columns

        # Non-$ properties should not return system column
        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "custom_prop"))
        assert "properties_group_system" not in columns
        assert "properties_group_custom" in columns
