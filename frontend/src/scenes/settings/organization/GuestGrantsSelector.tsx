import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { pluralize } from 'lib/utils/strings'

import { GuestGrantPreviewItem, GuestGrantResource, guestGrantsLogic } from './guestGrantsLogic'

const RESOURCES: { value: GuestGrantResource; label: string }[] = [
    { value: 'dashboard', label: 'Dashboards' },
    { value: 'insight', label: 'Insights' },
    { value: 'notebook', label: 'Notebooks' },
]

function PreviewItem({ item }: { item: GuestGrantPreviewItem }): JSX.Element {
    const label = RESOURCES.find((resource) => resource.value === item.resource)?.label ?? item.resource
    const insights = item.includes.filter((include) => include.resource === 'insight')
    const recordingCount = item.includes.length - insights.length
    return (
        <div className="flex flex-col gap-1">
            <div className="font-semibold">{item.name ?? `All ${label.toLowerCase()}`}</div>
            {insights.map((insight) => (
                <div key={insight.id} className="text-secondary pl-3">
                    {insight.name || 'Untitled insight'}
                </div>
            ))}
            {recordingCount > 0 && <div className="text-secondary pl-3">{pluralize(recordingCount, 'recording')}</div>}
            {item.loading && <LemonSkeleton className="h-4 w-32 ml-3" />}
        </div>
    )
}

export function GuestGrantsSelector({ inviteIndex }: { inviteIndex: number }): JSX.Element {
    const logic = guestGrantsLogic({ inviteIndex })
    const {
        activeResource,
        search,
        options,
        optionsLoading,
        optionsSearching,
        hiddenOptionCount,
        previewItems,
        allSelected,
        selectedIds,
        selectedCounts,
    } = useValues(logic)
    const { setActiveResource, setSearch, toggleObject, toggleAll } = useActions(logic)
    const activeLabel = (RESOURCES.find((resource) => resource.value === activeResource)?.label ?? '').toLowerCase()

    return (
        <div className="@container/guest-grants flex flex-col gap-2" data-attr="invite-guest-grants">
            <div className="font-semibold">What this guest can view</div>
            <div className="grid grid-cols-1 gap-4 @2xl/guest-grants:grid-cols-[10rem_minmax(0,1fr)_14rem]">
                <nav
                    aria-label="Item types"
                    className="grid grid-cols-3 gap-1 content-start @2xl/guest-grants:grid-cols-1"
                >
                    {RESOURCES.map((resource) => (
                        <LemonButton
                            key={resource.value}
                            size="small"
                            fullWidth
                            active={resource.value === activeResource}
                            onClick={() => setActiveResource(resource.value)}
                            sideIcon={
                                selectedCounts[resource.value] ? (
                                    <span className="text-xs text-secondary">{selectedCounts[resource.value]}</span>
                                ) : null
                            }
                            data-attr={`invite-guest-grants-type-${resource.value}`}
                        >
                            {resource.label}
                        </LemonButton>
                    ))}
                </nav>
                <div className="flex flex-col gap-1 min-w-0">
                    <LemonInput
                        type="search"
                        size="small"
                        fullWidth
                        placeholder={`Search ${activeLabel}`}
                        value={search}
                        onChange={setSearch}
                        suffix={optionsSearching ? <Spinner /> : null}
                    />
                    <LemonCheckbox
                        className="py-1"
                        label={`All ${activeLabel}`}
                        checked={allSelected}
                        onChange={() => toggleAll(activeResource)}
                        data-attr="invite-guest-grant-all"
                    />
                    <div className="flex flex-col max-h-60 overflow-y-auto">
                        {optionsLoading ? (
                            <LemonSkeleton className="h-5 my-1" repeat={3} />
                        ) : !options.length ? (
                            <div className="text-secondary py-1">
                                {search ? `No ${activeLabel} match your search.` : `No ${activeLabel} yet.`}
                            </div>
                        ) : (
                            options.map((option) => (
                                <LemonCheckbox
                                    key={option.id}
                                    className="py-1"
                                    label={option.name}
                                    checked={allSelected || selectedIds.has(option.id)}
                                    disabledReason={allSelected ? `All ${activeLabel} are selected` : null}
                                    onChange={() => toggleObject(activeResource, option)}
                                    data-attr="invite-guest-grant-item"
                                />
                            ))
                        )}
                    </div>
                    {hiddenOptionCount > 0 && (
                        <div className="text-xs text-secondary">
                            Showing {options.length} of {options.length + hiddenOptionCount}. Search to find others.
                        </div>
                    )}
                </div>
                <div className="flex flex-col gap-3 @2xl/guest-grants:border-l @2xl/guest-grants:pl-4">
                    <div className="text-xs font-semibold text-secondary">They will see</div>
                    {!previewItems.length ? (
                        <div className="text-secondary">Nothing yet. Pick what they can view.</div>
                    ) : (
                        previewItems.map((item) => <PreviewItem key={`${item.resource}-${item.id}`} item={item} />)
                    )}
                </div>
            </div>
        </div>
    )
}
