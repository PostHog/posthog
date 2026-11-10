from django import forms
from django.contrib import admin

from posthog.ip_restrictions import validate_ip_restrictions
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions


class IPRestrictionsWidget(forms.SelectMultiple):
    template_name = "admin/widgets/ip_restrictions.html"

    class Media:
        js = ("admin/js/ip_restrictions.js",)


class IPRestrictionsField(forms.Field):
    def to_python(self, value: list[str] | None) -> list[str]:
        return [entry.strip() for entry in value or [] if entry.strip()]


class OrganizationIPRestrictionsForm(forms.ModelForm):
    ip_restrictions = IPRestrictionsField(
        required=False,
        initial=list,
        widget=IPRestrictionsWidget,
        label="IP restrictions",
        help_text=OrganizationIPRestrictions._meta.get_field("ip_restrictions").help_text,
    )

    class Meta:
        model = OrganizationIPRestrictions
        fields = ("enabled", "ip_restrictions")

    def clean_ip_restrictions(self) -> list[str]:
        values = self.cleaned_data["ip_restrictions"] or []
        try:
            return validate_ip_restrictions(values)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error


class OrganizationIPRestrictionsInline(admin.StackedInline):
    model = OrganizationIPRestrictions
    form = OrganizationIPRestrictionsForm
    verbose_name = "IP restrictions"
    verbose_name_plural = "IP restrictions"
    extra = 1
    max_num = 1
    fields = ("enabled", "ip_restrictions")
