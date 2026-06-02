from django import forms
from django.contrib import admin
from django.utils.html import format_html

from posthog.api.uploaded_media import FOUR_MEGABYTES, validate_image_file
from posthog.models.organization_custom_asset import OrganizationCustomAsset


class OrganizationCustomAssetInlineForm(forms.ModelForm):
    image = forms.ImageField(
        required=False,
        help_text="PNG, JPEG, GIF or WebP. Max 4MB. Uploading replaces the existing file.",
    )

    class Meta:
        model = OrganizationCustomAsset
        fields = ("key",)

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image is None:
            return image
        if image.size > FOUR_MEGABYTES:
            raise forms.ValidationError("Uploaded media must be less than 4MB")
        content_type = getattr(image, "content_type", "") or ""
        if not content_type.startswith("image/"):
            raise forms.ValidationError("Uploaded media must be an image")
        # Verify it really is an image (and not e.g. HTML with image magic bytes) before we store it.
        image.seek(0)
        content = image.read()
        image.seek(0)
        if not validate_image_file(content, user=0):
            raise forms.ValidationError("Uploaded media must be a valid image")
        return image

    def clean(self):
        cleaned = super().clean()
        # A brand-new asset row must carry a file — otherwise it would have no media to serve.
        if self.instance.pk is None and cleaned.get("key") and not cleaned.get("image"):
            self.add_error("image", "An image file must be provided for a new asset")
        return cleaned


class OrganizationCustomAssetInline(admin.TabularInline):
    extra = 1
    model = OrganizationCustomAsset
    form = OrganizationCustomAssetInlineForm
    fields = ("key", "image", "preview", "file_name", "created_by", "created_at")
    readonly_fields = ("preview", "file_name", "created_by", "created_at")

    @admin.display(description="Preview")
    def preview(self, obj):
        if obj and obj.pk and obj.media_location:
            return format_html(
                '<img src="/organization_custom_asset/{}" style="height: 40px; max-width: 120px;" />',
                obj.pk,
            )
        return "—"

    # Custom assets are staff-managed branding — gate every mutation on staff (defense in depth;
    # the admin site already requires staff).
    def has_add_permission(self, request, obj=None):
        return bool(request.user.is_staff)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_staff)

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_staff)
