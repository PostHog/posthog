# Hog function argument counts

Hog checks standard library argument counts for direct calls and functions stored in variables.
The Python and TypeScript native function registries define the minimum and maximum accepted counts.
The HogQL parity test checks both bounds against shared HogQL function names in these registries.

`JSONHas(json)` accepts no path components and returns `true`, preserving Hog's existing empty-path behavior.

Some Hog signatures are deliberately narrower than HogQL:

| Function     | Hog arguments | Reason                                                                                        |
| ------------ | ------------- | --------------------------------------------------------------------------------------------- |
| `range`      | 1–2           | The VM does not implement HogQL's step argument.                                              |
| `dateAdd`    | 3             | The VM requires unit, amount, and datetime; it does not implement the date/interval overload. |
| `toTimeZone` | 2             | Hog requires an explicit timezone; HogQL can supply the project's timezone.                   |

Accepting an argument does not imply that Hog implements every HogQL option. For compatibility,
`round`, `floor`, `toString`, `now`, `position`, `positionCaseInsensitive`, `dateTrunc`,
`toStartOfDay`, `toStartOfWeek`, `arraySort`, and `arrayReverseSort` accept and ignore trailing options.
For example, `round(19.99, 2)` returns `20`; Hog does not apply the precision argument.
