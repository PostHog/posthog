import pytest


from posthog.api.routing import TeamAndOrgViewSetMixin


class TestRouting:
    def test_cannot_override_special_methods(self):
        with pytest.raises(Exception) as e:

            class _TestViewSet1(TeamAndOrgViewSetMixin):
                def get_permissions(self):
                    pass

        assert (
            str(e.value)
            == "Method get_permissions is protected and should not be overridden. Add additional 'permission_classes' via the class attribute instead. Or in exceptional use cases use dangerously_get_permissions instead"
        )

        with pytest.raises(Exception) as e:

            class _TestViewSet2(TeamAndOrgViewSetMixin):
                def get_authenticators(self):
                    pass

        assert (
            str(e.value)
            == "Method get_authenticators is protected and should not be overridden. Add additional 'authentication_classes' via the class attribute instead"
        )

        with pytest.raises(Exception) as e:

            class _TestViewSet3(TeamAndOrgViewSetMixin):
                def get_queryset(self):
                    pass

        assert (
            str(e.value)
            == "Method get_queryset is protected and should not be overridden. Use safely_get_queryset instead"
        )

        with pytest.raises(Exception) as e:

            class _TestViewSet4(TeamAndOrgViewSetMixin):
                def get_object(self):
                    pass

        assert (
            str(e.value) == "Method get_object is protected and should not be overridden. Use safely_get_object instead"
        )
