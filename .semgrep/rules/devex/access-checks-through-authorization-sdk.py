# Test cases for access-checks-through-authorization-sdk.
# ruff: noqa


class UserAccessControl:
    def check_access_level_for_object(self, obj, required_level): ...
    def check_access_level_for_resource(self, resource, required_level): ...
    def check_access_level_for_ref(self, ref, required_level): ...
    def check_can_modify_access_levels_for_object(self, obj): ...
    def check_can_modify_access_levels_for_ref(self, ref): ...
    def access_level_for_object(self, obj): ...


class authorization:
    @staticmethod
    def check(resource, action, subject=None): ...


access = UserAccessControl()
scanner = object()
ref = object()
resource = object()

# ruleid: access-checks-through-authorization-sdk
access.check_access_level_for_object(scanner, "editor")

# ruleid: access-checks-through-authorization-sdk
access.check_access_level_for_resource("session_recording", required_level="viewer")

# ruleid: access-checks-through-authorization-sdk
access.check_access_level_for_ref(ref, required_level="viewer")

# ruleid: access-checks-through-authorization-sdk
access.check_can_modify_access_levels_for_object(scanner)

# ruleid: access-checks-through-authorization-sdk
access.check_can_modify_access_levels_for_ref(ref)


class View:
    user_access_control = UserAccessControl()

    def check(self):
        # ruleid: access-checks-through-authorization-sdk
        return self.user_access_control.check_access_level_for_object(scanner, required_level="viewer")


# ruleid: access-checks-through-authorization-sdk
if not UserAccessControl().check_access_level_for_resource("dashboard", "editor"):
    pass

# ok: access-checks-through-authorization-sdk
authorization.check(resource=resource, action="edit")

# ok: access-checks-through-authorization-sdk
access.access_level_for_object(scanner)

# ok: access-checks-through-authorization-sdk
access.check_access_level_for_object(scanner, "viewer")  # nosemgrep: access-checks-through-authorization-sdk
