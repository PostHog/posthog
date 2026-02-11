# Test file for no-unscoped-relatedfield semgrep rule
from rest_framework import serializers

# ruleid: unscoped-primary-key-related-field
field = serializers.PrimaryKeyRelatedField(queryset=Foo.objects.all())

# ruleid: unscoped-primary-key-related-field
field = serializers.PrimaryKeyRelatedField(queryset=Foo.objects.all(), required=False)

# ruleid: unscoped-primary-key-related-field
field = serializers.PrimaryKeyRelatedField(many=True, queryset=Bar.objects.all(), required=False)

# ok: unscoped-primary-key-related-field
field = serializers.PrimaryKeyRelatedField(read_only=True)

# ok: unscoped-primary-key-related-field
field = TeamScopedPrimaryKeyRelatedField(queryset=Foo.objects.all())

# ok: unscoped-primary-key-related-field
field = OrgScopedPrimaryKeyRelatedField(queryset=Foo.objects.all())
