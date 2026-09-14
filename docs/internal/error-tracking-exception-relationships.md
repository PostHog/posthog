# Exception relationship IDs

Cymbal preserves SDK-provided `mechanism.exception_id` and `mechanism.parent_id` when it parses and serializes `$exception_list`.
Both fields are optional non-negative integers.
Absent fields remain omitted, so SDKs that do not send relationship IDs keep their existing event shape.

The IDs describe relationships within one event.
The outermost exception has `mechanism.exception_id: 0` and no parent.
A nested exception has its own `mechanism.exception_id` and a `mechanism.parent_id` pointing to its parent entry.
`mechanism.source` describes the relationship, such as `cause` or `member`.

These numeric IDs are separate from the top-level `id` UUID that Cymbal generates for each exception entry.
Cymbal preserves the SDK values without using them to change fingerprinting or reorder the exception list.
Preserving the fields does not itself change the frontend's exception display.

The shared SDK contract is documented in [exception event metadata](https://github.com/PostHog/sdk-specs/blob/main/openspec/specs/exception-event-metadata/spec.md).
