# Generated by Django 3.2.16 on 2022-11-15 00:07

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('posthog', '0279_organization_feature_flags_access_level'),
        ('ee', '0013_silence_deprecated_tags_warnings'),
    ]

    operations = [
        migrations.CreateModel(
            name='Role',
            fields=[
                ('id', models.UUIDField(default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('feature_flags_access_level', models.PositiveSmallIntegerField(choices=[(21, 'Can only view feature flags'), (37, 'Can always edit feature flags'), (25, 'Default view unless role grants access')], default=37)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='roles', related_query_name='role', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='roles', related_query_name='role', to='posthog.organization')),
            ],
        ),
        migrations.CreateModel(
            name='RoleMembership',
            fields=[
                ('id', models.UUIDField(default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('role', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='roles', related_query_name='role', to='ee.role')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='role_memberships', related_query_name='role_membership', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='FeatureFlagRoleAccess',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('feature_flag', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='access', related_query_name='access', to='posthog.featureflag')),
                ('role', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feature_flag_access', related_query_name='feature_flag_access', to='ee.role')),
            ],
        ),
        migrations.AddConstraint(
            model_name='rolemembership',
            constraint=models.UniqueConstraint(fields=('role', 'user'), name='unique_user_and_role'),
        ),
        migrations.AddConstraint(
            model_name='role',
            constraint=models.UniqueConstraint(fields=('organization', 'name'), name='unique_role_name'),
        ),
        migrations.AddConstraint(
            model_name='featureflagroleaccess',
            constraint=models.UniqueConstraint(fields=('role', 'feature_flag'), name='unique_feature_flag_and_role'),
        ),
    ]
