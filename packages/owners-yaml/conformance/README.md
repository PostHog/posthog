# owners.yaml conformance suite

This directory holds test cases for the resolution rules of the `owners.yaml` format.
The cases are data, so an implementation in any language can run them.

The cases are normative together with [SPEC.md section 4](https://github.com/PostHog/posthog/blob/master/packages/owners-yaml/SPEC.md#4-resolution) and [section 5.2](https://github.com/PostHog/posthog/blob/master/packages/owners-yaml/SPEC.md#52-team-channels).
An implementation of those sections must give the expected result for every case that applies to it.

## Contents

- `cases/`: case files. Each file holds the cases for one topic.
- `case.schema.json`: a JSON Schema (draft 2020-12) for one case file.

## Case file format

A case file is a YAML mapping with one key, `cases`.
The value is a list of cases.
Each case is a mapping with these keys:

| Key        | Required | Type                            | Meaning                                                                                     |
| ---------- | -------- | ------------------------------- | ------------------------------------------------------------------------------------------- |
| `name`     | yes      | string                          | A sentence that states the behavior. It is unique in its file.                              |
| `files`    | yes      | mapping of string to string     | The repository. Each key is a file path relative to the root. Each value is the content.    |
| `purpose`  | no       | `slack` or `notifications`      | The channel purpose (section 5.2). `slack` is the purpose "people". The default is `slack`. |
| `producer` | no       | string                          | The producer for the channel lookup (section 5.2). The default is no producer.              |
| `expect`   | yes      | mapping of string to resolution | Each key is a path to resolve. Each value is the expected resolution of that path.          |

File paths in `files` use `/` as the separator.
A file content can be empty or can be text that is not valid YAML, because some cases test files that count as absent.

A path in `expect` is the input to the resolver, before normalization.
Some keys start with `./` or `/`, or contain `\`, to test step 1 of the algorithm.
A path in `expect` does not have to exist in `files`.

Each resolution is a mapping with these keys:

| Key                 | Type             | Meaning                                                                    |
| ------------------- | ---------------- | -------------------------------------------------------------------------- |
| `owners`            | list of strings  | The resolved owners, in order. The list is empty when there are no owners. |
| `unowned_by_design` | boolean          | `true` when the owners come from an explicit `owners: null`.               |
| `status`            | string           | The resolved status.                                                       |
| `source`            | string or `null` | The path of the file that set the owners, or `null` when no file did.      |
| `slack`             | string or `null` | The channel for the purpose and the producer of the case, or `null`.       |
| `additions`         | list of strings  | Optional, default empty. The owners of additions at the path (SPEC 3.6).   |

A case never leaves out one of the first five keys, so no value is implied.
A case that leaves out `additions` expects an empty list, so the cases that predate the field stay as they are.

An example case:

```yaml
cases:
  - name: a child file that sets only owners keeps the parent's status
    files:
      owners.yaml: |
        version: 1
        owners: team-a
        status: deprecated
      billing/owners.yaml: |
        version: 1
        owners: team-b
    expect:
      billing/x.py:
        owners: [team-b]
        unowned_by_design: false
        status: deprecated
        source: billing/owners.yaml
        slack: '#team-b'
```

## How a runner uses a case

For each case in each file in `cases/`:

1. Make a new empty directory. This directory is the repository root. It is not a git repository.
2. Write each entry of `files` to its path below the root. Make the parent directories first. Write the content exactly as given.
3. Resolve each key of `expect` as given, with the `purpose` and the `producer` of the case.
4. Compare all six keys of the result with the expected resolution. An expected resolution without `additions` expects an empty list. The order of `owners` and of `additions` is significant.
5. The case passes when every path in `expect` passes.

Give each test a name of the form `<file name>::<case name>`, such as `nearest-file.yaml::owners null marks paths as unowned by design`.
Before a run, a runner can validate each case file against `case.schema.json`.

## Cases that apply only to some implementations

- `aliases.yaml` applies only to an implementation that supports alias files ([SPEC.md section 6](https://github.com/PostHog/posthog/blob/master/packages/owners-yaml/SPEC.md#6-alias-files)). Its cases declare `product.yaml` in `alias_files`.
- `owners-yaml-extensions.yaml` is not part of the format. It tests the `team-CHANGEME` placeholder of `owners-yaml` ([SPEC.md section 8](https://github.com/PostHog/posthog/blob/master/packages/owners-yaml/SPEC.md#8-the-owners-yaml-reference-implementation)). Other implementations skip this file.
- A case with a `producer` applies only to an implementation that accepts a producer.

All other files apply to every implementation.

## Reference runner

The `owners-yaml` runner is [`tests/test_conformance.py`](https://github.com/PostHog/posthog/blob/master/packages/owners-yaml/tests/test_conformance.py).
From the repository root, run it with this command:

```sh
uv run pytest packages/owners-yaml/tests/test_conformance.py
```

## Add a case

1. Put the case in the file for its topic. Make a new file only for a new topic.
2. Write the `name` as a statement of the behavior.
3. Get each expected value from SPEC.md, then run the reference runner to confirm it.
4. When SPEC.md and a case disagree, the disagreement is a defect in SPEC.md ([section 4.3](https://github.com/PostHog/posthog/blob/master/packages/owners-yaml/SPEC.md#43-conformance)). Fix SPEC.md or the case, not only the implementation.
