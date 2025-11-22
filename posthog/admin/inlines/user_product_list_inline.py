from django import forms
from django.contrib import admin

from posthog.models.file_system.user_product_list import UserProductList
from posthog.products import Products


class UserProductListInlineForm(forms.ModelForm):
    class Meta:
        model = UserProductList
        fields = ["user", "product_path", "reason", "reason_text", "enabled"]

    def __init__(self, *args, **kwargs):
        # Extract parent_instance from kwargs if present (set by formset)
        self.parent_instance = kwargs.pop("parent_instance", None)
        super().__init__(*args, **kwargs)

        # Restrict reason to sales_led only and disable it
        self.fields["reason"].choices = [(UserProductList.Reason.SALES_LED, UserProductList.Reason.SALES_LED.label)]  # type: ignore
        self.fields["reason"].initial = UserProductList.Reason.SALES_LED
        self.fields["reason"].widget = forms.Select(choices=self.fields["reason"].choices)  # type: ignore
        self.fields["reason"].disabled = True

        # Set product_path choices from Products
        product_paths = Products.get_product_paths()
        self.fields["product_path"].widget = forms.Select(
            choices=[("", "---------")] + [(path, path) for path in product_paths]
        )

        # Filter users to only show users from the team's organization
        parent_instance = getattr(self, "parent_instance", None)

        # Determine which team to use for filtering
        team = None
        if self.instance and self.instance.pk:
            # Check if instance has team_id set (safer than accessing .team directly)
            if hasattr(self.instance, "team_id") and self.instance.team_id:
                try:
                    team = self.instance.team
                except UserProductList.team.RelatedObjectDoesNotExist:
                    pass

        # If no team from instance, use parent (for new instances)
        if not team and parent_instance:
            team = parent_instance

        if team and hasattr(team, "organization_id") and team.organization_id:
            from posthog.models.user import User

            self.fields["user"].queryset = User.objects.filter(  # type: ignore
                organization_membership__organization_id=team.organization_id
            ).distinct()

        self.fields["reason_text"].required = False
        self.fields["reason_text"].widget.attrs["rows"] = 8
        self.fields["reason_text"].widget.attrs["placeholder"] = (
            "We default to displaying this message in the UI when adding a new product: \"We've added this product to your sidebar because we believe you'd benefit from it! Your TAM will reach out to help you learn more about it.\""
            "\nYou can override with a custom message here, make it personal!"
            "\n\nExample: Hey, it's Rafael. I believe you'll like using our new SQL Editor! I went ahead and gave you 1,000,000 free rows, Merry Christmas!"
        )

        # Set enabled default to True and read-only
        self.fields["enabled"].initial = True
        self.fields["enabled"].disabled = True

    def clean(self):
        cleaned_data = super().clean()

        if not cleaned_data:
            return cleaned_data

        user = cleaned_data.get("user")

        # Only validate for new instances (when creating, not editing)
        if user and not self.instance.pk:
            if user.allow_sidebar_suggestions is False:
                from django.core.exceptions import ValidationError

                raise ValidationError(
                    {
                        "user": f"User {user.email} has disabled sidebar suggestions. Cannot create UserProductList items for this user."
                    }
                )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # For existing instances, only save reason_text and enabled
        if instance.pk:
            # Reload the instance to preserve existing values
            existing = UserProductList.objects.get(pk=instance.pk)
            instance.user = existing.user
            instance.product_path = existing.product_path
            instance.reason = existing.reason
            instance.team = existing.team
            # Only reason_text and enabled can be changed
        else:
            # For new instances, validate allow_sidebar_suggestions
            if instance.user and instance.user.allow_sidebar_suggestions is False:
                from django.core.exceptions import ValidationError

                raise ValidationError(
                    f"User {instance.user.email} has disabled sidebar suggestions. Cannot create UserProductList items for this user."
                )

            # Set defaults
            if not instance.reason:
                instance.reason = UserProductList.Reason.SALES_LED
            # Set team from parent instance
            parent_instance = getattr(self, "parent_instance", None)
            if not instance.team_id and parent_instance:
                instance.team = parent_instance

        if commit:
            instance.save()
        return instance


class UserProductListInline(admin.TabularInline):
    model = UserProductList
    form = UserProductListInlineForm
    extra = 1
    fields = ("user", "product_path", "reason", "reason_text", "enabled")
    readonly_fields = ("id",)
    verbose_name = "Sales-led Product Addition"
    verbose_name_plural = "Sales-led Product Additions"
    classes = ("collapse",)

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        # Store parent instance (Team) in form for filtering users and setting team
        original_init = formset.form.__init__

        def form_init(self, *args, **kwargs):
            kwargs["parent_instance"] = obj
            result = original_init(self, *args, **kwargs)
            return result

        formset.form.__init__ = form_init  # type: ignore
        return formset

    def get_queryset(self, request):
        # Only show items with sales_led reason in the inline
        qs = super().get_queryset(request)
        return qs.filter(reason=UserProductList.Reason.SALES_LED)

    def has_change_permission(self, request, obj=None):
        # Allow editing reason_text for existing sales-led items
        return True

    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion from inline
        return False
