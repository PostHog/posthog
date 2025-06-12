import { STL as HOG_STL } from '@posthog/hogvm'
import { IconCode } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { useState } from 'react'

export type HogFunctionTemplateOption = {
    key: string
    description: string
    example: string
}

export type HogFunctionTemplateSuggestionsProps = {
    templating: 'hog' | 'liquid'
    setTemplating?: (templating: 'hog' | 'liquid') => void
    value: string
    onOptionSelect: (option: HogFunctionTemplateOption) => void
}

const HOG_USAGE_EXAMPLES: HogFunctionTemplateOption[] = [
    {
        key: 'ternary',
        example: `$1 = true ? 'Yes' : 'No'`,
        description: 'Ternary operation (if this then that else other)',
    },
    {
        key: 'default',
        example: `$1 ?? 'Default value'`,
        description: 'Default value (if this is null or undefined, use this)',
    },
]

const HOG_STL_EXAMPLES: HogFunctionTemplateOption[] = Object.entries(HOG_STL).map(([key, value]) => ({
    key,
    example: value.example,
    description: value.description,
}))

function HogFunctionTemplateSuggestionsItem({
    option,
    onSelect,
}: {
    option: HogFunctionTemplateOption
    onSelect: (option: HogFunctionTemplateOption) => void
}): JSX.Element {
    return (
        <LemonButton fullWidth role="menuitem" size="small" onClick={() => onSelect(option)}>
            <div className="flex-col flex-1">
                <code className="text-sm font-semibold font-monospace">{option.example}</code>
                <div className="text-xs text-secondary">{option.description}</div>
            </div>
        </LemonButton>
    )
}

export function HogFunctionTemplateSuggestions({
    templating,
    setTemplating,
    value,
    onOptionSelect,
}: HogFunctionTemplateSuggestionsProps): JSX.Element {
    const [search, setSearch] = useState('')

    // TODO
    // * Add a logic
    // * Add a search
    // * Use the correct search logic for the template language
    // * Have a way to search for event / properties etc.

    return (
        <div className="flex overflow-hidden flex-col flex-1 gap-1 max-w-100">
            <div className="flex flex-col gap-1 p-2 flex-0">
                <div className="flex gap-1">
                    <LemonInput
                        type="search"
                        placeholder="Search templating options"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />

                    {setTemplating ? (
                        <FlaggedFeature flag="cdp-hog-input-liquid">
                            <LemonSelect
                                value={templating}
                                onChange={setTemplating}
                                options={[
                                    { label: 'Hog', value: 'hog' },
                                    { label: 'Liquid', value: 'liquid' },
                                ]}
                                tooltip="Change the templating language"
                            />
                        </FlaggedFeature>
                    ) : null}
                </div>
                <div className="text-xs text-secondary">
                    Below are a list of available functions for templating your inputs using <b>{templating}</b>.
                    <Link to="https://posthog.com/docs/cdp/destinations/customizing-destinations#customizing-payload">
                        Learn more
                    </Link>
                </div>
            </div>
            <ul className="flex overflow-y-auto flex-col flex-1 gap-px p-2 border-t max-w-100">
                {HOG_USAGE_EXAMPLES.map((value) => (
                    <li key={value.key}>
                        <HogFunctionTemplateSuggestionsItem option={value} onSelect={onOptionSelect} />
                    </li>
                ))}

                <LemonDivider />
                {HOG_STL_EXAMPLES.map((value) => (
                    <li key={value.key}>
                        <HogFunctionTemplateSuggestionsItem option={value} onSelect={onOptionSelect} />
                    </li>
                ))}
            </ul>
        </div>
    )
}

export function HogFunctionTemplateSuggestionsButton({
    onOptionSelect,
    ...props
}: HogFunctionTemplateSuggestionsProps): JSX.Element {
    const [showPopover, setShowPopover] = useState(false) // TODO: Move this to the logic somehow

    const _onOptionSelect = (option: HogFunctionTemplateOption): void => {
        onOptionSelect(option)
        setShowPopover(false)
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            actionable
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={<HogFunctionTemplateSuggestions {...props} onOptionSelect={_onOptionSelect} />}
            overflowHidden
        >
            <LemonButton
                size="small"
                icon={<IconCode />}
                tooltip="Supports templating - click to see available options"
            />
        </LemonDropdown>
    )
}
