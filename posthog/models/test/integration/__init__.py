# Package marker, not optional: posthog/models/test/ is a package, so without this file
# pytest names these modules by bare basename (test_github, test_jira, ...) and they
# collide with same-named test files elsewhere in the repo, knocking those out of
# collection in any session that spans both trees.
