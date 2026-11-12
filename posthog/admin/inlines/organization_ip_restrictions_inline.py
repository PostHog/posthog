from django import forms
from django.contrib import admin

from posthog.ip_restrictions import validate_ip_restrictions
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions


class OrganizationIPRestrictionsForm(forms.ModelForm):
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
