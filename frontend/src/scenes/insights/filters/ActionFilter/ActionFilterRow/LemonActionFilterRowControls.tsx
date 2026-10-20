import { IconCopy, IconFilter, IconGroupIntersect, IconPencil, IconTrash } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { ActionFilterRowControls, ActionFilterRowControlsArgs } from './actionFilterRowControls'
import { ActionFilterRowMenu } from './ActionFilterRowMenu'

export function buildLemonActionFilterRowControls({
    index,
    propertyFilterCount,
    propertyFiltersVisible,
    propertyFiltersDisabledReason,
    addFilterDocLink,
    inlineEventsDocLink,
    enablePopup,
    canCombine,
    onToggleFilters,
    onRename,
    onDuplicate,
    onCombine,
    onDelete,
    menu,
}: ActionFilterRowControlsArgs): ActionFilterRowControls {
    const propertyFiltersButton = (
        <IconWithCount key="property-filter" count={propertyFilterCount} showZero={false}>
            <LemonButton
                icon={<IconFilter />}
                title="Show filters"
                data-attr={`show-prop-filter-${index}`}
                noPadding
                active={propertyFiltersVisible}
                onClick={() => {
                    onToggleFilters()
                }}
                disabledReason={propertyFiltersDisabledReason}
                tooltip="Show filters"
                tooltipDocLink={addFilterDocLink}
            />
        </IconWithCount>
    )

    const renameRowButton = (
        <LemonButton
            key="rename"
            icon={<IconPencil />}
            title="Rename graph series"
            data-attr={`show-prop-rename-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
                onRename()
            }}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Rename' : undefined}
        </LemonButton>
    )

    const duplicateRowButton = (
        <LemonButton
            key="duplicate"
            icon={<IconCopy />}
            title="Duplicate graph series"
            data-attr={`show-prop-duplicate-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
                onDuplicate()
            }}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Duplicate' : undefined}
        </LemonButton>
    )

    const combineInlineButton = (
        <LemonButton
            key="combine-inline"
            icon={<IconGroupIntersect />}
            data-attr={`show-prop-combine-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
                onCombine()
            }}
            tooltip="Count multiple events as a single event"
            tooltipDocLink={inlineEventsDocLink}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Combine' : undefined}
        </LemonButton>
    )

    const deleteButton = (
        <LemonButton
            key="delete"
            status={enablePopup ? 'danger' : 'default'}
            icon={<IconTrash />}
            title="Delete graph series"
            data-attr={`delete-prop-filter-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
                onDelete()
            }}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Delete' : undefined}
        </LemonButton>
    )

    return {
        propertyFiltersButton,
        renameRowButton,
        duplicateRowButton,
        combineInlineButton,
        deleteButton,
        menu: (
            <ActionFilterRowMenu
                index={index}
                {...menu}
                renameRowButton={renameRowButton}
                duplicateRowButton={duplicateRowButton}
                deleteButton={deleteButton}
                combineButton={canCombine ? combineInlineButton : null}
            />
        ),
    }
}
