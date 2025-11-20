import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { FeatureFlagFiltersSection } from 'scenes/feature-flags/FeatureFlagFilters'
import { urls } from 'scenes/urls'

import { FeatureFlagType } from '~/types'

import { selectExistingFeatureFlagModalLogic } from './selectExistingFeatureFlagModalLogic'

export const SelectExistingFeatureFlagModal = ({
    onClose,
    onSelect,
}: {
    onClose: () => void
    onSelect: (flag: FeatureFlagType) => void
}): JSX.Element => {
    const { featureFlags, featureFlagsLoading, filters, pagination, isModalOpen, isEvaluationTagsRequired } = useValues(
        selectExistingFeatureFlagModalLogic
    )
    const { setFilters, resetFilters } = useActions(selectExistingFeatureFlagModalLogic)

    const hasEvaluationTags = (flag: FeatureFlagType): boolean => {
        return (flag.evaluation_tags?.length ?? 0) > 0
    }

    const handleClose = (): void => {
        resetFilters()
        onClose()
    }

    const filtersSection = (
        <div className="mb-4">
            <FeatureFlagFiltersSection
                filters={filters}
                setFeatureFlagsFilters={setFilters}
                searchPlaceholder="Search for feature flags"
                filtersConfig={{ search: true }}
            />
        </div>
    )

    // Filter out flags without evaluation tags when requirement is enabled
    // NOTE: This is client-side filtering which means pagination may show fewer results
    // than expected (e.g., fetched 10 but filtered to 3). Consider server-side filtering
    // in the future for better UX with large flag lists.
    const filteredFlags = isEvaluationTagsRequired
        ? featureFlags.results.filter((flag) => hasEvaluationTags(flag))
        : featureFlags.results

    return (
        <LemonModal isOpen={isModalOpen} onClose={handleClose} title="Choose an existing feature flag" width="50%">
            <div className="deprecated-space-y-2">
                <div className="text-muted mb-2 max-w-xl">
                    Select an existing multivariate feature flag to use with this experiment. The feature flag must use
                    multiple variants with <code>'control'</code> as the first.
                </div>
                {filtersSection}
                <LemonTable
                    id="ff"
                    dataSource={filteredFlags}
                    loading={featureFlagsLoading}
                    useURLForSorting={false}
                    columns={[
                        {
                            title: 'Key',
                            dataIndex: 'key',
                            sorter: (a, b) => (a.key || '').localeCompare(b.key || ''),
                            render: (key, flag) => (
                                <div className="flex items-center">
                                    <div className="font-semibold">{key}</div>
                                    <Link
                                        to={urls.featureFlag(flag.id as number)}
                                        target="_blank"
                                        className="flex items-center"
                                    >
                                        <IconOpenInNew className="ml-1" />
                                    </Link>
                                </div>
                            ),
                        },
                        {
                            title: 'Name',
                            dataIndex: 'name',
                            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
                        },
                        {
                            title: null,
                            render: function RenderActions(_, flag) {
                                return (
                                    <div className="flex items-center justify-end">
                                        <LemonButton
                                            size="xsmall"
                                            type="primary"
                                            onClick={() => {
                                                onSelect(flag)
                                                handleClose()
                                            }}
                                        >
                                            Select
                                        </LemonButton>
                                    </div>
                                )
                            },
                        },
                    ]}
                    emptyState="No feature flags match these filters."
                    pagination={pagination}
                    onSort={(newSorting) =>
                        setFilters({
                            order: newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined,
                            page: 1,
                        })
                    }
                />
            </div>
        </LemonModal>
    )
}
