import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonLabel, LemonModal, LemonSelect, LemonTag } from '@posthog/lemon-ui'
import { LemonBanner, LemonButton, LemonColorButton, LemonColorPicker, LemonSegmentedButton } from '@posthog/lemon-ui'
import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { BreakdownTag } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { dataColorThemesLogic } from 'scenes/settings/environment/dataColorThemesLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { DashboardMode } from '~/types'

import {
    BreakdownColorConfig,
    BreakdownValueAndType,
    COHORT_BREAKDOWN_PROPERTY_KEY,
    denormalizeBreakdownValue,
    findBreakdownColorConfig,
    parseBreakdownPropertyKey,
} from './dashboardBreakdownColors'
import { ColorsModalPrototypeVariants, dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'
import { dashboardLogic } from './dashboardLogic'

type BreakdownColorRow = BreakdownColorConfig & { pinnedConfig?: BreakdownColorConfig }

const HELP_TEXT =
    'Colors are grouped by breakdown property. A value shown on two or more insights gets one color across the ' +
    'dashboard, and each property picks its colors on its own. Values on a single insight keep their own colors. ' +
    'Pick a color to pin a value to it.'

function BreakdownPropertyGroupTitle({
    breakdownProperty,
    variant,
}: {
    breakdownProperty?: string
    variant: ColorsModalPrototypeVariants['propertyDisplay']
}): JSX.Element {
    if (breakdownProperty == null) {
        // The property-less group holds entries that apply under every property, like the funnel baseline.
        return <LemonTag type="muted">All properties</LemonTag>
    }
    if (breakdownProperty === COHORT_BREAKDOWN_PROPERTY_KEY) {
        return <LemonTag type="muted">Cohorts</LemonTag>
    }
    const parts = parseBreakdownPropertyKey(breakdownProperty)
    if (variant === 'pill') {
        return (
            <div className="flex flex-wrap items-center gap-1">
                {parts.map((part, index) => (
                    <BreakdownTag key={index} breakdown={part.property} breakdownType={part.type} size="small" />
                ))}
            </div>
        )
    }
    return (
        <span>
            {parts.map((part, index) => (
                <span key={index}>
                    {index > 0 ? <span className="text-muted-alt"> · </span> : null}
                    <PropertyKeyInfo value={part.property} disablePopover disableIcon />
                </span>
            ))}
        </span>
    )
}

export function DashboardInsightColorsModal(): JSX.Element {
    const { isOpen, insightTilesLoading, breakdownValueGroups, prototypeVariants } = useValues(
        dashboardInsightColorsModalLogic
    )
    const { hideInsightColorsModal, setPrototypeVariant } = useActions(dashboardInsightColorsModalLogic)

    const { themes: _themes, themesLoading } = useValues(dataColorThemesLogic)

    const { effectiveBreakdownColors, dataColorThemeId, dashboardMode } = useValues(dashboardLogic)
    const { setBreakdownColorConfig, setDataColorThemeId, setDashboardMode } = useActions(dashboardLogic)

    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { allCohorts } = useValues(cohortsModel)

    const themes = _themes || []

    const ensureEditMode = (): void => {
        if (dashboardMode !== DashboardMode.Edit) {
            setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardInsightColorsModal)
        }
    }

    const toRow = (breakdownValue: BreakdownValueAndType): BreakdownColorRow => {
        const config = findBreakdownColorConfig(
            effectiveBreakdownColors,
            breakdownValue.breakdownValue,
            breakdownValue.breakdownType,
            breakdownValue.breakdownProperty
        )
        return {
            ...breakdownValue,
            colorToken: config?.colorToken || null,
            source: config?.source,
            pinnedConfig: config,
        }
    }

    const columns: LemonTableColumns<BreakdownColorRow> = [
        {
            title: 'Breakdown',
            key: 'breakdown_value',
            render: (_, { breakdownValue, breakdownType }) => {
                const breakdownFilter: BreakdownFilter = { breakdown_type: breakdownType }
                const breakdownLabel = formatBreakdownLabel(
                    denormalizeBreakdownValue(breakdownValue),
                    breakdownFilter,
                    allCohorts?.results,
                    formatPropertyValueForDisplay
                )
                const formattedLabel = stringWithWBR(breakdownLabel, 20)

                return <span>{formattedLabel}</span>
            },
        },
        {
            title: 'Color',
            key: 'color',
            render: (_, { colorToken, source, pinnedConfig, ...config }) => {
                const isManual = colorToken !== null && source !== 'auto'
                // Clearing must target the entry that provides the pin: a property-less legacy pin
                // cleared from a scoped row would otherwise survive and keep coloring other properties.
                const reset = (): void => {
                    ensureEditMode()
                    setBreakdownColorConfig({ ...(pinnedConfig ?? config), colorToken: null, source: 'manual' })
                }
                const pin = (colorToken: BreakdownColorConfig['colorToken']): void => {
                    ensureEditMode()
                    setBreakdownColorConfig({ ...config, colorToken, source: 'manual' })
                }

                if (prototypeVariants.colorState === 'swatch') {
                    // One control carries the whole state: a filled swatch when pinned, a subtler
                    // one when auto-assigned, the unset glyph when the value has no dashboard color.
                    // Reset shows up only once the user has pinned, so nothing competes with it.
                    return (
                        <div className="flex items-center gap-1">
                            <LemonColorPicker
                                selectedColorToken={colorToken}
                                onSelectColorToken={pin}
                                themeId={dataColorThemeId}
                                customButton={
                                    <LemonColorButton
                                        colorToken={colorToken}
                                        themeId={dataColorThemeId}
                                        type={isManual ? 'secondary' : 'tertiary'}
                                        tooltip={
                                            isManual
                                                ? 'Pinned color. Click to change.'
                                                : colorToken !== null
                                                  ? 'Automatic color. Click to pin your own.'
                                                  : 'No dashboard color. Click to pin one.'
                                        }
                                    />
                                }
                            />
                            {isManual ? (
                                <LemonButton
                                    size="small"
                                    icon={<IconX />}
                                    tooltip="Reset to automatic color"
                                    onClick={reset}
                                />
                            ) : null}
                        </div>
                    )
                }

                return (
                    <div className="flex items-center gap-2">
                        <LemonColorPicker
                            selectedColorToken={colorToken}
                            onSelectColorToken={pin}
                            customButton={
                                colorToken === null ? (
                                    <LemonButton type="tertiary">Customize color</LemonButton>
                                ) : undefined
                            }
                            themeId={dataColorThemeId}
                        />
                        {source === 'auto' ? (
                            <LemonTag type="muted">Auto</LemonTag>
                        ) : colorToken !== null ? (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                tooltip="Reset to automatic color"
                                onClick={reset}
                            >
                                Reset
                            </LemonButton>
                        ) : null}
                    </div>
                )
            },
        },
    ]

    return (
        <LemonModal
            title="Customize breakdown colors"
            isOpen={isOpen}
            onClose={hideInsightColorsModal}
            maxWidth="42rem"
        >
            <LemonBanner type="info" className="mb-4">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                    <span className="font-semibold">Prototype options</span>
                    <LemonSegmentedButton
                        size="xsmall"
                        value={prototypeVariants.propertyDisplay}
                        onChange={(propertyDisplay) => setPrototypeVariant({ propertyDisplay })}
                        options={[
                            { value: 'pill', label: 'Pill headers' },
                            { value: 'text', label: 'Text headers' },
                        ]}
                    />
                    <LemonSegmentedButton
                        size="xsmall"
                        value={prototypeVariants.colorState}
                        onChange={(colorState) => setPrototypeVariant({ colorState })}
                        options={[
                            { value: 'swatch', label: 'Swatch' },
                            { value: 'tag', label: 'Picker + tag' },
                        ]}
                    />
                    <LemonSegmentedButton
                        size="xsmall"
                        value={prototypeVariants.helpText}
                        onChange={(helpText) => setPrototypeVariant({ helpText })}
                        options={[
                            { value: 'notice', label: 'Help as notice' },
                            { value: 'paragraph', label: 'Help as text' },
                        ]}
                    />
                </div>
            </LemonBanner>

            <LemonLabel info="Select a color theme for all insights on this dashboard. If a theme is selected, it will be applied to all series and breakdowns.">
                Color theme
            </LemonLabel>
            <LemonSelect
                className="mt-2"
                value={dataColorThemeId || null}
                placeholder="Defined by insight"
                onChange={(id) => {
                    ensureEditMode()
                    setDataColorThemeId(id)
                }}
                loading={themesLoading}
                options={themes.map((theme) => ({ value: theme.id, label: theme.name }))}
            />

            <LemonLabel className="mt-4">Breakdown colors</LemonLabel>
            {prototypeVariants.helpText === 'notice' ? (
                <LemonBanner type="info" className="mt-2 mb-4">
                    {HELP_TEXT}
                </LemonBanner>
            ) : (
                <p className="text-muted-alt mt-2 mb-4">{HELP_TEXT}</p>
            )}
            {breakdownValueGroups.length === 0 ? (
                <LemonTable columns={columns} dataSource={[]} loading={insightTilesLoading || undefined} />
            ) : (
                breakdownValueGroups.map((group) => (
                    <div key={group.breakdownProperty ?? ''} className="mb-4">
                        <LemonLabel className="mb-1">
                            <BreakdownPropertyGroupTitle
                                breakdownProperty={group.breakdownProperty}
                                variant={prototypeVariants.propertyDisplay}
                            />
                        </LemonLabel>
                        <LemonTable columns={columns} dataSource={group.values.map(toRow)} showHeader={false} />
                    </div>
                ))
            )}
            {insightTilesLoading ? (
                <p className="text-muted-alt mt-2">Tiles are still loading. More breakdown values may appear.</p>
            ) : null}
        </LemonModal>
    )
}
