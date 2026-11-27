import { IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

import { PropertyDefinition } from './materializedColumnsLogic'
import { useAssignSlotForm } from './useAssignSlotForm'

export function CreateSlotModal(): JSX.Element {
    const {
        availableProperties,
        availablePropertiesLoading,
        filteredProperties,
        selectedProperty,
        selectedPropertyId,
        setSelectedPropertyId,
        searchTerm,
        setSearchTerm,
        isSubmitting,
        handleSubmit,
        close,
    } = useAssignSlotForm()

    return (
        <LemonModal
            isOpen
            onClose={close}
            title="Assign Materialized Column Slot"
            width="36rem"
            footer={
                <>
                    <LemonButton type="secondary" onClick={close}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={isSubmitting}
                        disabledReason={!selectedPropertyId ? 'Please select a property' : undefined}
                    >
                        Queue for materialization
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <p className="text-muted">
                    Select a property to queue for materialization. The slot starts in <strong>PENDING</strong> state;
                    the next weekly backfill cycle will assign it a column, run the historical backfill, and transition
                    it to <strong>READY</strong>. Until then HogQL falls back to JSON extraction for this property.
                </p>

                <div>
                    <LemonLabel>Property to materialize</LemonLabel>
                    {selectedProperty ? (
                        <LemonButton
                            fullWidth
                            onClick={() => setSelectedPropertyId(null)}
                            sideAction={{
                                icon: <IconX />,
                                tooltip: 'Clear selection',
                                onClick: () => setSelectedPropertyId(null),
                            }}
                        >
                            <span className="flex items-center justify-between gap-2 flex-1">
                                <span>{selectedProperty.name}</span>
                                <LemonTag type="default" size="small">
                                    {selectedProperty.property_type}
                                </LemonTag>
                            </span>
                        </LemonButton>
                    ) : (
                        <div className="deprecated-space-y-2">
                            <LemonInput
                                type="search"
                                placeholder="Search properties..."
                                value={searchTerm}
                                onChange={setSearchTerm}
                                fullWidth
                                autoFocus
                            />
                            <div className="max-h-60 overflow-y-auto">
                                {availablePropertiesLoading ? (
                                    <div className="p-4 text-center text-muted">Loading properties...</div>
                                ) : filteredProperties.length === 0 ? (
                                    <div className="p-4 text-center text-muted">
                                        {searchTerm ? 'No properties match your search' : 'No properties available'}
                                    </div>
                                ) : (
                                    <ul className="deprecated-space-y-px">
                                        {filteredProperties.map((prop: PropertyDefinition) => (
                                            <li key={prop.id}>
                                                <LemonButton
                                                    fullWidth
                                                    role="menuitem"
                                                    size="small"
                                                    onClick={() => {
                                                        setSelectedPropertyId(prop.id)
                                                        setSearchTerm('')
                                                    }}
                                                >
                                                    <span className="flex items-center justify-between gap-2 flex-1">
                                                        <span className="truncate">{prop.name}</span>
                                                        <LemonTag type="default" size="small">
                                                            {prop.property_type}
                                                        </LemonTag>
                                                    </span>
                                                </LemonButton>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                {availableProperties.length === 0 && !availablePropertiesLoading && (
                    <div className="bg-warning-highlight text-warning rounded p-3 text-sm">
                        No properties available for materialization. All eligible properties have either been
                        materialized or don't have a property_type set.
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
