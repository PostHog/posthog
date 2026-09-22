# JSONDropKeys Stateless Fixtures

Each test has a `<name>.tsv` input and a matching `<name>.reference` expected output. These integration fixtures run `JSONDropKeys(['a'])`. Files ending in `.fail.tsv` are expected to fail, and their `.reference` file contains the required stderr substring.

| Test                                   | Purpose                                                                                       |
| -------------------------------------- | --------------------------------------------------------------------------------------------- |
| `drop_top_level_a`                     | Removes every top-level `a` key while preserving unrelated keys and duplicate unrelated keys. |
| `drop_nested_a_and_expand_dotted_keys` | Drops top-level `a` values and verifies dotted non-dropped keys are expanded consistently.    |
| `large_integer`                        | Preserves large integer values while dropping only requested keys.                            |
| `root_array`                           | Drops keys from objects when the root JSON value is an array.                                 |
| `malformed_json.fail`                  | Verifies malformed JSON fails instead of being hidden.                                        |
