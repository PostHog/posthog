import json

from django.contrib.admin import AdminSite, ModelAdmin, helpers
from django.contrib.admin.options import FORMFIELD_FOR_DBFIELD_DEFAULTS
from django.contrib.admin.templatetags import admin_list
from django.db import models
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.admin.json_fields import PrettyJSONWidget, install_pretty_json_admin, render_json_for_admin

LONG_DICT = {f"key_{i}": f"value_{i}" * 5 for i in range(10)}
LONG_LIST = [f"item_{i}" * 10 for i in range(10)]


class TestPrettyJSONWidget(SimpleTestCase):
    def test_format_value_pretty_prints_json_strings(self):
        widget = PrettyJSONWidget()
        assert widget.format_value('{"a": 1, "b": [2, 3]}') == '{\n  "a": 1,\n  "b": [\n    2,\n    3\n  ]\n}'

    def test_format_value_leaves_invalid_json_untouched(self):
        widget = PrettyJSONWidget()
        assert widget.format_value("{not valid json") == "{not valid json"

    def test_format_value_none(self):
        widget = PrettyJSONWidget()
        assert widget.format_value(None) is None

    def test_render_wraps_textarea_with_toolbar_and_script(self):
        rendered = PrettyJSONWidget().render("config", '{"a": 1}')
        assert "<textarea" in rendered
        assert 'class="ph-json-widget"' in rendered
        assert "Format JSON" in rendered
        assert "__phJsonWidgetInit" in rendered

    def test_render_escapes_html_in_value(self):
        rendered = PrettyJSONWidget().render("config", '{"a": "<script>alert(1)</script>"}')
        assert "<script>alert(1)</script>" not in rendered
        assert "&lt;script&gt;" in rendered

    def test_rows_grow_with_content(self):
        many_lines = json.dumps({f"k{i}": i for i in range(12)})
        assert 'rows="15"' in PrettyJSONWidget().render("config", many_lines)

    def test_rows_capped_for_huge_content(self):
        huge = json.dumps({f"k{i}": i for i in range(200)})
        assert 'rows="30"' in PrettyJSONWidget().render("config", huge)

    def test_explicit_rows_attr_is_respected(self):
        widget = PrettyJSONWidget(attrs={"rows": 5})
        rendered = widget.render("config", json.dumps({f"k{i}": i for i in range(50)}))
        assert 'rows="5"' in rendered


class TestRenderJsonForAdmin(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_dict", {}, "{}"),
            ("empty_list", [], "[]"),
            ("short_dict", {"a": 1}, "{&quot;a&quot;: 1}"),
            ("scalar", 42, "42"),
        ]
    )
    def test_short_values_render_inline_code(self, _name, value, expected_compact):
        rendered = render_json_for_admin(value)
        assert rendered is not None
        assert rendered.startswith("<code")
        assert expected_compact in rendered

    @parameterized.expand(
        [
            ("dict", LONG_DICT, "{…} 10 keys"),
            ("list", LONG_LIST, "[…] 10 items"),
        ]
    )
    def test_long_values_render_collapsible_details(self, _name, value, expected_hint):
        rendered = render_json_for_admin(value)
        assert rendered is not None
        assert rendered.startswith("<details")
        assert not rendered.startswith("<details open")
        assert expected_hint in rendered
        assert "<pre" in rendered

    def test_prefer_open_expands_small_values(self):
        rendered = render_json_for_admin(LONG_DICT, prefer_open=True)
        assert rendered is not None
        assert rendered.startswith("<details open")

    def test_prefer_open_keeps_huge_values_collapsed(self):
        huge = {f"key_{i}": f"value_{i}" for i in range(100)}
        rendered = render_json_for_admin(huge, prefer_open=True)
        assert rendered is not None
        assert not rendered.startswith("<details open")

    def test_escapes_html_in_value(self):
        rendered = render_json_for_admin({"a": "</pre><script>alert(1)</script>" + "x" * 200})
        assert rendered is not None
        assert "<script>" not in rendered
        assert "&lt;script&gt;" in rendered

    def test_non_serializable_value_returns_none(self):
        assert render_json_for_admin({"a": object()}) is None


class TestInstallPrettyJsonAdmin(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        install_pretty_json_admin()

    def test_install_is_idempotent(self):
        install_pretty_json_admin()
        install_pretty_json_admin()
        rendered = helpers.display_for_field(LONG_DICT, models.JSONField(), "-")
        assert rendered.count("<details") == 1

    def test_json_field_default_widget_is_pretty(self):
        assert FORMFIELD_FOR_DBFIELD_DEFAULTS[models.JSONField]["widget"] is PrettyJSONWidget

    def test_model_admin_formfield_uses_pretty_widget(self):
        from posthog.models import Team

        model_admin = ModelAdmin(Team, AdminSite())
        formfield = model_admin.formfield_for_dbfield(Team._meta.get_field("extra_settings"), request=None)
        assert formfield is not None
        assert isinstance(formfield.widget, PrettyJSONWidget)

    def test_readonly_detail_rendering_is_expanded(self):
        rendered = helpers.display_for_field(LONG_DICT, models.JSONField(), "-")
        assert rendered.startswith("<details open")

    def test_changelist_rendering_is_collapsed(self):
        rendered = admin_list.display_for_field(LONG_DICT, models.JSONField(), "-")
        assert rendered.startswith("<details")
        assert not rendered.startswith("<details open")

    def test_short_json_renders_inline(self):
        rendered = helpers.display_for_field({"a": 1}, models.JSONField(), "-")
        assert rendered.startswith("<code")

    def test_scalar_json_falls_through_to_default(self):
        rendered = helpers.display_for_field("plain string", models.JSONField(), "-")
        assert rendered == '"plain string"'

    def test_non_json_field_unchanged(self):
        rendered = helpers.display_for_field("plain string", models.CharField(), "-")
        assert rendered == "plain string"

    def test_json_field_with_choices_keeps_label(self):
        field = models.JSONField(choices=[({"a": 1}, "Option A")])
        assert helpers.display_for_field({"a": 1}, field, "-") == "Option A"
