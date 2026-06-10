"""Admin-wide pretty rendering and editing of model ``JSONField`` values.

``install_pretty_json_admin()`` (called from ``register_all_admin()`` before any
``ModelAdmin`` is instantiated) wires two things up for every admin, including
product and third-party ones:

- Editable JSON fields default to :class:`PrettyJSONWidget` — a monospace
  textarea with the value pretty-printed server-side, plus client-side
  validation feedback and a "Format JSON" button. Per-admin
  ``formfield_overrides`` still take precedence.
- Read-only fields and changelist columns render through
  :func:`render_json_for_admin` — short values inline as ``<code>``, longer
  ones as a collapsible ``<details>`` block with indented, syntax-safe JSON.
"""

import json
from collections.abc import Callable
from typing import Any

from django import forms
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

# Compact JSON at or below this length renders inline without a fold.
JSON_INLINE_MAX_LENGTH = 120
# Pretty JSON with at most this many lines renders expanded in read-only detail views.
JSON_DETAIL_OPEN_MAX_LINES = 40
JSON_SUMMARY_PREVIEW_LENGTH = 80

_MONOSPACE = "font-family: var(--font-family-monospace, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);"

_CODE_STYLE = (
    "padding: 1px 5px; border-radius: 4px; font-size: 12px;"
    " background: var(--darkened-bg, #f8f8f8); border: 1px solid var(--hairline-color, #e8e8e8);" + _MONOSPACE
)
_DETAILS_STYLE = "max-width: 80em;"
_SUMMARY_STYLE = (
    "cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12px;" + _MONOSPACE
)
_SUMMARY_PREVIEW_STYLE = "color: var(--body-quiet-color, #666); margin-left: 6px;"
_PRE_STYLE = (
    "margin: 4px 0 0; padding: 8px 10px; max-height: 600px; overflow: auto;"
    " background: var(--darkened-bg, #f8f8f8); border: 1px solid var(--hairline-color, #e8e8e8);"
    " border-radius: 4px; font-size: 12px; line-height: 1.45; white-space: pre-wrap; word-break: break-word;"
    + _MONOSPACE
)

_TOOLBAR_HTML = (
    '<div class="ph-json-toolbar" style="margin-top: 4px; display: flex; gap: 8px; align-items: center;">'
    '<button type="button" class="button ph-json-format" style="padding: 2px 8px;">Format JSON</button>'
    '<span class="ph-json-status" style="font-size: 11px;"></span>'
    "</div>"
)

# Emitted once per widget but guarded so only the first copy runs. Event
# delegation on `document` keeps it working for inline formset rows that the
# admin clones dynamically after page load.
_WIDGET_SCRIPT_HTML = """\
<script>
(function () {
    if (window.__phJsonWidgetInit) { return; }
    window.__phJsonWidgetInit = true;
    function validate(textarea) {
        var root = textarea.closest('.ph-json-widget');
        var status = root && root.querySelector('.ph-json-status');
        if (!status) { return; }
        var text = textarea.value.trim();
        if (!text) {
            status.textContent = '';
            textarea.style.borderColor = '';
            return;
        }
        try {
            JSON.parse(text);
            status.textContent = '\\u2713 valid JSON';
            status.style.color = '#28a745';
            textarea.style.borderColor = '';
        } catch (err) {
            status.textContent = '\\u2717 ' + err.message;
            status.style.color = '#ba2121';
            textarea.style.borderColor = '#ba2121';
        }
    }
    document.addEventListener('input', function (event) {
        var target = event.target;
        if (target && target.matches && target.matches('.ph-json-widget textarea')) {
            validate(target);
        }
    });
    document.addEventListener('click', function (event) {
        var button = event.target && event.target.closest ? event.target.closest('.ph-json-format') : null;
        if (!button) { return; }
        event.preventDefault();
        var root = button.closest('.ph-json-widget');
        var textarea = root && root.querySelector('textarea');
        if (!textarea) { return; }
        var text = textarea.value.trim();
        if (text) {
            try {
                textarea.value = JSON.stringify(JSON.parse(text), null, 2);
            } catch (err) { /* leave invalid input untouched; validate() will flag it */ }
        }
        validate(textarea);
    });
})();
</script>"""

_installed = False


class PrettyJSONWidget(forms.Textarea):
    """Textarea for JSON values: pretty-printed server-side, with client-side
    validation feedback and a "Format JSON" button."""

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        # Auto-size rows to the formatted value unless the caller pinned them.
        self._auto_rows = not (attrs and "rows" in attrs)
        default_attrs: dict[str, Any] = {
            "class": "vLargeTextField ph-json-input",
            "spellcheck": "false",
            "autocapitalize": "off",
            "autocomplete": "off",
            "style": "tab-size: 2; " + _MONOSPACE,
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    def format_value(self, value: Any) -> str | None:
        formatted = super().format_value(value)
        if formatted is None:
            return None
        try:
            return json.dumps(json.loads(formatted), indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            # Not valid JSON — e.g. re-displaying rejected user input. Show it untouched.
            return formatted

    def get_context(self, name: str, value: Any, attrs: dict[str, Any] | None) -> dict[str, Any]:
        context = super().get_context(name, value, attrs)
        if self._auto_rows and not (attrs and "rows" in attrs):
            rendered_value = context["widget"]["value"] or ""
            context["widget"]["attrs"]["rows"] = max(4, min(rendered_value.count("\n") + 2, 30))
        return context

    def render(self, name: str, value: Any, attrs: dict[str, Any] | None = None, renderer: Any = None) -> SafeString:
        textarea = super().render(name, value, attrs, renderer)
        return format_html(
            '<div class="ph-json-widget" style="display: inline-block; max-width: 100%;">{}{}</div>{}',
            textarea,
            mark_safe(_TOOLBAR_HTML),
            mark_safe(_WIDGET_SCRIPT_HTML),
        )


def render_json_for_admin(
    value: Any,
    encoder: type[json.JSONEncoder] | None = None,
    prefer_open: bool = False,
) -> SafeString | None:
    """Render a JSON value as display HTML: short values inline as ``<code>``,
    longer ones as a collapsible pretty-printed ``<details>`` block.

    Returns ``None`` when the value is not JSON-serializable so callers can
    fall back to Django's default rendering.
    """
    try:
        compact = json.dumps(value, ensure_ascii=False, cls=encoder)
        pretty = json.dumps(value, indent=2, ensure_ascii=False, cls=encoder)
    except TypeError:
        return None

    if len(compact) <= JSON_INLINE_MAX_LENGTH:
        return format_html('<code style="{}">{}</code>', _CODE_STYLE, compact)

    if isinstance(value, dict):
        size_hint = f"{{…}} {len(value)} key{'s' if len(value) != 1 else ''}"
    elif isinstance(value, list):
        size_hint = f"[…] {len(value)} item{'s' if len(value) != 1 else ''}"
    else:
        size_hint = f"{len(compact)} chars"

    open_attr = " open" if prefer_open and pretty.count("\n") + 1 <= JSON_DETAIL_OPEN_MAX_LINES else ""
    return format_html(
        '<details{} style="{}"><summary style="{}">{}<span style="{}">{}</span></summary><pre style="{}">{}</pre></details>',
        mark_safe(open_attr),
        _DETAILS_STYLE,
        _SUMMARY_STYLE,
        size_hint,
        _SUMMARY_PREVIEW_STYLE,
        compact[:JSON_SUMMARY_PREVIEW_LENGTH] + "…",
        _PRE_STYLE,
        pretty,
    )


def install_pretty_json_admin() -> None:
    """Apply pretty JSON rendering/editing across the whole admin. Idempotent.

    Must run before any ``ModelAdmin`` is instantiated: each instance snapshots
    ``FORMFIELD_FOR_DBFIELD_DEFAULTS`` in ``BaseModelAdmin.__init__``.
    """
    global _installed
    if _installed:
        return
    _installed = True

    from django.contrib.admin import helpers, options, utils
    from django.contrib.admin.templatetags import admin_list
    from django.db import models

    # Editable JSON fields (including JSONField subclasses, via the MRO lookup
    # in `formfield_for_dbfield`) get the pretty widget by default. Admins that
    # declare their own override for JSONField keep it.
    options.FORMFIELD_FOR_DBFIELD_DEFAULTS.setdefault(models.JSONField, {"widget": PrettyJSONWidget})

    original_display_for_field = utils.display_for_field

    def make_display_for_field(prefer_open: bool) -> Callable[..., Any]:
        def display_for_field_with_pretty_json(
            value: Any, field: Any, empty_value_display: str, avoid_link: bool = False
        ) -> Any:
            # Only intercept containers: scalars are already short and readable,
            # and fields with choices keep their human label.
            if (
                isinstance(field, models.JSONField)
                and not getattr(field, "flatchoices", None)
                and isinstance(value, dict | list)
            ):
                rendered = render_json_for_admin(value, encoder=field.encoder, prefer_open=prefer_open)
                if rendered is not None:
                    return rendered
            return original_display_for_field(value, field, empty_value_display, avoid_link)

        return display_for_field_with_pretty_json

    # `helpers` renders read-only detail fields — expand reasonably-sized values
    # there. `admin_list` renders changelist columns — keep those folded so rows
    # stay compact. Each module imported the function by name, so patch all of
    # them (plus `utils` for any other caller).
    utils.display_for_field = make_display_for_field(prefer_open=False)  # ty: ignore[invalid-assignment]
    admin_list.display_for_field = make_display_for_field(prefer_open=False)
    helpers.display_for_field = make_display_for_field(prefer_open=True)
