import { IconCode, IconExternal } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { useState } from 'react'

import {
    CyclotronJobTemplateOption,
    cyclotronJobTemplateSuggestionsLogic,
} from './cyclotronJobTemplateSuggestionsLogic'

export type CyclotronJobTemplateSuggestionsProps = {
    templating: 'hog' | 'liquid'
    setTemplating?: (templating: 'hog' | 'liquid') => void
    value: string
    onOptionSelect: (option: CyclotronJobTemplateOption) => void
}

function CyclotronJobTemplateSuggestionsItem({
    option,
    onSelect,
}: {
    option: CyclotronJobTemplateOption
    onSelect: (option: CyclotronJobTemplateOption) => void
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

export function CyclotronJobTemplateSuggestions({
    templating,
    setTemplating,
    onOptionSelect,
}: CyclotronJobTemplateSuggestionsProps): JSX.Element {
    const logic = cyclotronJobTemplateSuggestionsLogic({ templating })
    const { search, optionsFiltered } = useValues(logic)
    const { setSearch } = useActions(logic)

    // FUTURE IDEAS:
    // * Allow searching taxonomic properties to auto fill the data (events, person properties etc.)
    // * Inline documentation for liquid
    // * Have the last selected text selection be passed in so we can fill it in the appropriate place

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
                    Below are a list of available functions for templating your inputs using <b>{templating}</b>.{' '}
                    <Link to="https://posthog.com/docs/cdp/destinations/customizing-destinations#customizing-payload">
                        Learn more
                    </Link>
                </div>
            </div>
            <ul className="flex overflow-y-auto flex-col flex-1 gap-px p-2 border-t max-w-100">
                {optionsFiltered.map((value) => (
                    <li key={value.key}>
                        <CyclotronJobTemplateSuggestionsItem option={value} onSelect={onOptionSelect} />
                    </li>
                ))}

                {templating === 'liquid' ? (
                    <li>
                        <LemonButton
                            size="small"
                            sideIcon={<IconExternal />}
                            to="https://liquidjs.com/filters/overview.html"
                            targetBlank
                        >
                            Liquid documentation
                        </LemonButton>
                    </li>
                ) : null}
            </ul>
        </div>
    )
}

export function CyclotronJobTemplateSuggestionsButton({
    onOptionSelect,
    ...props
}: CyclotronJobTemplateSuggestionsProps): JSX.Element {
    const [showPopover, setShowPopover] = useState(false) // TODO: Move this to the logic somehow

    const _onOptionSelect = (option: CyclotronJobTemplateOption): void => {
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
            overlay={<CyclotronJobTemplateSuggestions {...props} onOptionSelect={_onOptionSelect} />}
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
