import { IconCopy, IconFilter, IconGroupIntersect, IconPencil, IconTrash } from '@posthog/icons'

import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'

import { ActionFilterRowControls, ActionFilterRowControlsArgs } from './actionFilterRowControls'
import { QuillActionFilterRowMenu } from './QuillActionFilterRowMenu'

export function buildQuillActionFilterRowControls({
    index,
    propertyFilterCount,
    propertyFiltersVisible,
    propertyFiltersDisabledReason,
    canCombine,
    onToggleFilters,
    onRename,
    onDuplicate,
    onCombine,
    onDelete,
    menu,
}: ActionFilterRowControlsArgs): ActionFilterRowControls {
    return {
        propertyFiltersButton: (
            <QuillIconButton
                key="property-filter"
                label="Show filters"
                icon={<IconFilter />}
                count={propertyFilterCount}
                aria-pressed={propertyFiltersVisible}
                data-attr={`show-prop-filter-${index}`}
                onClick={onToggleFilters}
                disabledReason={propertyFiltersDisabledReason}
            />
        ),
        renameRowButton: (
            <QuillIconButton
                key="rename"
                label="Rename graph series"
                icon={<IconPencil />}
                data-attr={`show-prop-rename-${index}`}
                onClick={onRename}
            />
        ),
        duplicateRowButton: (
            <QuillIconButton
                key="duplicate"
                label="Duplicate graph series"
                icon={<IconCopy />}
                data-attr={`show-prop-duplicate-${index}`}
                onClick={onDuplicate}
            />
        ),
        combineInlineButton: (
            <QuillIconButton
                key="combine-inline"
                label="Count multiple events as a single event"
                icon={<IconGroupIntersect />}
                data-attr={`show-prop-combine-${index}`}
                onClick={onCombine}
            />
        ),
        deleteButton: (
            <QuillIconButton
                key="delete"
                label="Delete graph series"
                icon={<IconTrash />}
                data-attr={`delete-prop-filter-${index}`}
                onClick={onDelete}
            />
        ),
        menu: (
            <QuillActionFilterRowMenu
                index={index}
                {...menu}
                onRename={onRename}
                onDuplicate={onDuplicate}
                onDelete={onDelete}
                onCombine={canCombine ? onCombine : null}
            />
        ),
    }
}
