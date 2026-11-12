// @ts-nocheck
// Test fixture for the lemon-button-no-overflow-clip rule.

// ruleid: lemon-button-no-overflow-clip
const Truncated = (
    <LemonButton type="secondary" className="min-w-26 max-w-48 truncate">
        Any tags
    </LemonButton>
)

// ruleid: lemon-button-no-overflow-clip
const TypeAfterClass = (
    <LemonButton className="overflow-hidden" type="primary" onClick={save}>
        Save
    </LemonButton>
)

// ruleid: lemon-button-no-overflow-clip
const Conditional = (
    <LemonButton
        type="secondary"
        fullWidth
        className={cn('min-w-0 overflow-hidden rounded', selected && 'ring-2 ring-accent')}
    >
        Tile
    </LemonButton>
)

// ruleid: lemon-button-no-overflow-clip
const SelectAxis = <LemonSelect className="overflow-x-hidden" value={value} options={options} onChange={onChange} />

// ok: lemon-button-no-overflow-clip
const TruncateProp = (
    <LemonButton type="secondary" truncate className="min-w-26 max-w-48">
        Any tags
    </LemonButton>
)

// ok: lemon-button-no-overflow-clip
const InnerSpan = (
    <LemonButton type="secondary" className="max-w-full">
        <span className="truncate">{label}</span>
    </LemonButton>
)

// A tertiary button has no border to clip.
// ok: lemon-button-no-overflow-clip
const Tertiary = (
    <LemonButton type="tertiary" className="min-w-0 truncate">
        Link
    </LemonButton>
)

// ok: lemon-button-no-overflow-clip
const VariableNamedTruncate = (
    <LemonButton type="secondary" className={truncate ? 'max-w-40' : undefined}>
        Owner
    </LemonButton>
)

// ok: lemon-button-no-overflow-clip
const Visible = (
    <LemonButton type="secondary" className="overflow-visible">
        Visible
    </LemonButton>
)
