import { LemonButton, LemonSelect, LemonTag } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'

import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SelectableCard } from 'products/experiments/frontend/components/SelectableCard'

import { resolveFilterTestAccounts } from '../exposureContract'
import {
    EXPOSURE_CRITERIA_INTRO,
    EXPOSURE_MODE_TITLES,
    ExposureCriteriaEditors,
    type ExposureCriteriaModalProps,
    MULTIPLE_VARIANT_HANDLING_OPTIONS,
    exposureModeDescription,
    multipleVariantHandlingHelp,
    useExposureCriteriaModal,
} from './exposureCriteriaModel'
import { QuillExposureCriteriaModal } from './QuillExposureCriteriaModal'

export function ExposureCriteriaModal(props: ExposureCriteriaModalProps): JSX.Element | null {
    const model = useExposureCriteriaModal(props)
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav && resultsRedesign) {
        return <QuillExposureCriteriaModal model={model} />
    }

    const {
        isOpen,
        close,
        save,
        saveDisabledReason,
        exposureCriteria,
        setExposureCriteria,
        resolvedExposureEvent,
        hasFilters,
        warehouseExposure,
        mode,
        selectMode,
        modes,
    } = model

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={close}
            width={860}
            title="Edit exposure criteria"
            zIndex="1169"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton form="edit-experiment-exposure-form" type="secondary" onClick={close}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={save}
                        type="primary"
                        disabledReason={saveDisabledReason}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="text-secondary text-sm mb-4">{EXPOSURE_CRITERIA_INTRO}</div>
            <div className="flex flex-wrap gap-4 mb-4">
                {modes.map(({ mode: option, blockedReason }) => (
                    <SelectableCard
                        key={option}
                        title={EXPOSURE_MODE_TITLES[option]}
                        description={exposureModeDescription(option, <LemonTag>{resolvedExposureEvent}</LemonTag>)}
                        selected={mode === option}
                        disabled={!!blockedReason}
                        disabledReason={blockedReason ?? ''}
                        data-attr={option === 'warehouse-native' ? 'experiment-exposure-warehouse-native' : undefined}
                        onClick={() => selectMode(option)}
                    />
                ))}
            </div>
            <ExposureCriteriaEditors model={model} />
            <div className="w-[405px]">
                <div className="mb-4">
                    <label className="block text-sm font-medium text-default mb-2">Multiple variant handling</label>
                    <LemonSelect
                        value={exposureCriteria?.multiple_variant_handling || 'exclude'}
                        onChange={(value) => {
                            setExposureCriteria({
                                ...exposureCriteria,
                                multiple_variant_handling: value as 'exclude' | 'first_seen',
                            })
                        }}
                        options={MULTIPLE_VARIANT_HANDLING_OPTIONS.map((option) => ({
                            value: option.value,
                            label: option.label,
                            'data-attr': option.dataAttr,
                        }))}
                        placeholder="Select handling method"
                        fullWidth
                    />
                    <div className="text-xs text-muted mt-1">
                        {multipleVariantHandlingHelp(exposureCriteria?.multiple_variant_handling)}
                    </div>
                </div>
                {/* Test account filters read PostHog person and event properties, which warehouse rows do not have */}
                {!warehouseExposure && (
                    <TestAccountFilterSwitch
                        checked={hasFilters && resolveFilterTestAccounts(exposureCriteria)}
                        onChange={(checked: boolean) => {
                            setExposureCriteria({
                                ...exposureCriteria,
                                filterTestAccounts: checked,
                            })
                        }}
                        fullWidth
                    />
                )}
            </div>
        </LemonModal>
    )
}
