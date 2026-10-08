# A test class that takes a database it never uses

`BaseTest`, `APIBaseTest`, and `NonAtomicBaseTest` inherit Django `TestCase`.
A class on one of them needs a database to run.
`setUpTestData` writes an organization, a project, a team and a user for the class, and every test method runs inside a transaction that is rolled back afterwards.
A class that only asserts on constants and pure functions pays all of that and reads no row.
The base class is the whole difference: on `django.test.SimpleTestCase` the same assertions need no database at all, so the file runs anywhere, including a checkout with no test database.

## The check

`posthog/test/repo_invariants/test_database_free_test_classes.py`, with its list in `database_free_test_classes_baseline.txt`.

It scans the repo on every backend pull request in the `repo-checks` job and compares what it finds against the frozen list, so the count can fall but never rise.

It reads each class body for any name that reaches the database, so it cannot see a call several helper levels down.
A class it misses stays missed, which is the safe error.
It also leaves out two kinds of class, because the fix below would be wrong for them: a class the repo inherits from somewhere, whose own body names nothing while every subclass reaches the database, and a class with no test method of its own, which is infrastructure rather than a test.

What a failure looks like: `database_free_test_classes_baseline.txt no longer matches the repo`, followed by `+` lines for classes the branch added and `-` lines for classes it removed.

## What to do when it trips

Work out which of three cases you are in.

**The class really needs no database.**
This is the common case, and the fix is the base class:

```python
from django.test import SimpleTestCase

class TestScopeRules(SimpleTestCase):
    def test_write_downgrades_to_read(self) -> None:
        assert downgrade_scopes_to_read_only("x:write") == "x:read"
```

`SimpleTestCase` refuses database access outright, so a passing run is proof the class never needed one.
Run the class before you believe it.

**The class needs a database through a helper the check cannot see.**
It reads the class body only, so a fixture built inside an imported helper is invisible to it.
Keep the base class and keep the class's baseline line, in the same change.

Say what the helper does when you explain it in review.
"It needs the database" repeats the code; "`seed_billing_fixtures()` writes the plan rows" tells the next reader where to look.

**The class only touches the database in part of its cases.**
Split it.
Move the pure cases to a `SimpleTestCase` class and leave the rest on `BaseTest`.
That takes the pure cases off the database without weakening the rest, and it is usually the honest shape when a class has grown two jobs.

## Regenerating the baseline

Only to ratchet down, or after a rename or a move:

```sh
python posthog/test/repo_invariants/test_database_free_test_classes.py
```

The file records removals as well as additions, so a class you fixed has to leave the list in the same change.
That is what stops the file going stale behind the code.

## Writing a new test class

Pick the base from what the test actually reads:

| The class needs                      | Base                            |
| ------------------------------------ | ------------------------------- |
| nothing from Django but its settings | `django.test.SimpleTestCase`    |
| no framework at all                  | `unittest.TestCase`             |
| an org, team, or user fixture        | `posthog.test.base.BaseTest`    |
| an authenticated API round trip      | `posthog.test.base.APIBaseTest` |

Reach up that list only when the regression you named in the gate genuinely lives there.
A serializer's field validation, a pure transformation, and a set of constants all belong on the first two rows.
