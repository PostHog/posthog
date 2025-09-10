from posthog.clickhouse.property_groups import property_groups


class TestSystemPropertyGroup:
    def test_system_property_group_definition_exists(self):
        """Test that the system property group is defined for events tables"""
        # Check sharded_events table has system property group
        assert "system" in property_groups.get_groups()["sharded_events"]["properties"]

        # Check events table has system property group
        assert "system" in property_groups.get_groups()["events"]["properties"]

    def test_system_property_group_matches_dollar_properties(self):
        """Test that the system property group correctly identifies $ properties"""
        system_group = property_groups.get_groups()["sharded_events"]["properties"]["system"]

        # Should match properties starting with $ (but not $ai_ or $feature/)
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

        # Should not match AI properties (they have their own group)
        assert not system_group.contains("$ai_language")
        assert not system_group.contains("$ai_input")
        assert not system_group.contains("$ai_output_choices")

        # Should not match feature flag properties (they have their own group)
        assert not system_group.contains("$feature/my-flag")
        assert not system_group.contains("$feature/test")

    def test_system_property_group_column_name(self):
        """Test that the system property group generates the correct column name"""
        system_group = property_groups.get_groups()["sharded_events"]["properties"]["system"]

        column_name = system_group.get_column_name("properties", "system")
        assert column_name == "properties_group_system"

    def test_property_groups_are_mutually_exclusive(self):
        """Test that system, AI, and feature flag property groups are mutually exclusive"""
        system_group = property_groups.get_groups()["sharded_events"]["properties"]["system"]
        ai_group = property_groups.get_groups()["sharded_events"]["properties"]["ai"]
        feature_flags_group = property_groups.get_groups()["sharded_events"]["properties"]["feature_flags"]

        # AI properties should only match AI group, not system
        assert ai_group.contains("$ai_language")
        assert not system_group.contains("$ai_language")

        # Feature flag properties should only match feature_flags group, not system
        assert feature_flags_group.contains("$feature/my-flag")
        assert not system_group.contains("$feature/my-flag")

        # Regular $ properties should only match system group
        assert system_group.contains("$browser")
        assert not ai_group.contains("$browser")
        assert not feature_flags_group.contains("$browser")

        # System group acts as catchall for other $ properties
        assert system_group.contains("$unknown_property")
        assert not ai_group.contains("$unknown_property")
        assert not feature_flags_group.contains("$unknown_property")

    def test_get_property_group_columns_returns_correct_groups(self):
        """Test that get_property_group_columns returns correct columns for different property types"""
        # Regular system properties should only return system column
        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$browser"))
        assert "properties_group_system" in columns
        assert "properties_group_ai" not in columns
        assert "properties_group_feature_flags" not in columns

        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$device_type"))
        assert "properties_group_system" in columns
        assert "properties_group_ai" not in columns
        assert "properties_group_feature_flags" not in columns

        # AI properties should only return AI column (not system)
        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$ai_language"))
        assert "properties_group_ai" in columns
        assert "properties_group_system" not in columns

        # Feature flag properties should only return feature_flags column (not system)
        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$feature/test"))
        assert "properties_group_feature_flags" in columns
        assert "properties_group_system" not in columns

        # Non-$ properties should only return custom column
        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "custom_prop"))
        assert "properties_group_custom" in columns
        assert "properties_group_system" not in columns
