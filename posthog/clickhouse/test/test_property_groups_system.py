from posthog.clickhouse.property_groups import property_groups


class TestSystemPropertyGroup:
    """
    Tests for the system property group.

    Note: The system property group is currently marked as hidden=True,
    which means it won't be used by HogQL queries until it's unhidden
    """

    def test_system_property_group_definition_exists(self):
        """Test that the system property group is defined for events tables"""
        # Check sharded_events table has system property group
        assert "system" in property_groups.get_groups()["sharded_events"]["properties"]

        # Check events table has system property group
        assert "system" in property_groups.get_groups()["events"]["properties"]

    def test_system_property_group_matches_dollar_properties(self):
        """Test that the system property group correctly identifies $ properties"""
        system_group = property_groups.get_groups()["sharded_events"]["properties"]["system"]

        # The system group is currently hidden, so contains() will return False
        # Test the underlying key_filter_function instead
        assert system_group.key_filter_function("$browser")
        assert system_group.key_filter_function("$browser_version")
        assert system_group.key_filter_function("$os")
        assert system_group.key_filter_function("$device_type")
        assert system_group.key_filter_function("$current_url")
        assert system_group.key_filter_function("$host")
        assert system_group.key_filter_function("$pathname")
        assert system_group.key_filter_function("$screen_height")
        assert system_group.key_filter_function("$screen_width")
        assert system_group.key_filter_function("$lib")
        assert system_group.key_filter_function("$lib_version")
        assert system_group.key_filter_function("$insert_id")
        assert system_group.key_filter_function("$time")
        assert system_group.key_filter_function("$device_id")
        assert system_group.key_filter_function("$user_id")
        assert system_group.key_filter_function("$ip")

        # Should not match properties not starting with $
        assert not system_group.key_filter_function("browser")
        assert not system_group.key_filter_function("custom_property")
        assert not system_group.key_filter_function("utm_source")
        assert not system_group.key_filter_function("token")

        # Should not match AI properties (they have their own group)
        assert not system_group.key_filter_function("$ai_language")
        assert not system_group.key_filter_function("$ai_input")
        assert not system_group.key_filter_function("$ai_output_choices")

        # Should not match feature flag properties (they have their own group)
        assert not system_group.key_filter_function("$feature/my-flag")
        assert not system_group.key_filter_function("$feature/test")

    def test_system_property_group_column_name(self):
        """Test that the system property group generates the correct column name"""
        system_group = property_groups.get_groups()["sharded_events"]["properties"]["system"]

        column_name = system_group.get_column_name("properties", "system")
        assert column_name == "properties_group_system"

    def test_system_property_group_is_hidden(self):
        """Test that the system property group is currently hidden"""
        system_group = property_groups.get_groups()["sharded_events"]["properties"]["system"]

        # Verify the group is hidden
        assert system_group.hidden

        # When hidden, contains() should always return False even for matching properties
        assert not system_group.contains("$browser")
        assert not system_group.contains("$os")

        # But the underlying key_filter_function should still work correctly
        assert system_group.key_filter_function("$browser")
        assert system_group.key_filter_function("$os")

    def test_property_groups_are_mutually_exclusive(self):
        """Test that system, AI, and feature flag property groups are mutually exclusive"""
        system_group = property_groups.get_groups()["sharded_events"]["properties"]["system"]
        ai_group = property_groups.get_groups()["sharded_events"]["properties"]["ai"]
        feature_flags_group = property_groups.get_groups()["sharded_events"]["properties"]["feature_flags"]

        # AI properties should only match AI group, not system
        assert ai_group.contains("$ai_language")
        assert not system_group.key_filter_function("$ai_language")  # Use key_filter_function for hidden group

        # Feature flag properties should only match feature_flags group, not system
        assert feature_flags_group.contains("$feature/my-flag")
        assert not system_group.key_filter_function("$feature/my-flag")  # Use key_filter_function for hidden group

        # Regular $ properties should only match system group
        assert system_group.key_filter_function("$browser")  # Use key_filter_function for hidden group
        assert not ai_group.contains("$browser")
        assert not feature_flags_group.contains("$browser")

        # System group acts as catchall for other $ properties
        assert system_group.key_filter_function("$unknown_property")  # Use key_filter_function for hidden group
        assert not ai_group.contains("$unknown_property")
        assert not feature_flags_group.contains("$unknown_property")

    def test_get_property_group_columns_returns_correct_groups(self):
        """Test that get_property_group_columns returns correct columns for different property types"""
        # Since system group is hidden, it won't be returned by get_property_group_columns
        # Regular system properties will not return any column while hidden
        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$browser"))
        assert "properties_group_system" not in columns  # Hidden groups are not returned
        assert "properties_group_ai" not in columns
        assert "properties_group_feature_flags" not in columns
        assert "properties_group_custom" not in columns

        columns = list(property_groups.get_property_group_columns("sharded_events", "properties", "$device_type"))
        assert "properties_group_system" not in columns  # Hidden groups are not returned
        assert "properties_group_ai" not in columns
        assert "properties_group_feature_flags" not in columns
        assert "properties_group_custom" not in columns

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
