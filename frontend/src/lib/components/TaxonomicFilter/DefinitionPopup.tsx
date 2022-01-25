import './DefinitionPopup.scss'
import React from 'react'
import clsx from 'clsx'
import { definitionPopupLogic, DefinitionPopupState } from 'lib/components/TaxonomicFilter/definitionPopupLogic'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'
import { KeyMapping } from '~/types'

interface HeaderProps {
    title: React.ReactNode
    headerTitle: React.ReactNode
    icon: React.ReactNode
}
interface DefinitionPopupProps {
    children: React.ReactNode
}

// Wrapper
function DefinitionPopup({ title, icon, headerTitle, children }: DefinitionPopupProps & HeaderProps): JSX.Element {
    const { state } = useValues(definitionPopupLogic)
    return (
        <div className={clsx('definition-popup', state)}>
            <Header title={title} headerTitle={headerTitle} icon={icon} />
            {children}
        </div>
    )
}

function Header({ title, headerTitle, icon }: HeaderProps): JSX.Element {
    const { state } = useValues(definitionPopupLogic)
    const { setPopupState } = useActions(definitionPopupLogic)
    const isEdit = state === DefinitionPopupState.Edit

    return (
        <div className="definition-popup-header">
            {isEdit ? (
                <div className="definition-popup-header-row">
                    <div className="definition-popup-title">
                        {icon} {title}
                    </div>
                    <a onClick={() => setPopupState(DefinitionPopupState.View)}>Edit</a>
                </div>
            ) : (
                <>
                    <div className="definition-popup-header-row">
                        <div className="definition-popup-header-row-title">{headerTitle}</div>
                        <a onClick={() => setPopupState(DefinitionPopupState.Edit)}>View</a>
                    </div>
                    <div className="definition-popup-title">
                        {icon} {title}
                    </div>
                </>
            )}
        </div>
    )
}

function Description({ description }: { description: string }): JSX.Element {
    return <div className="definition-popup-description">{description}</div>
}

function DescriptionEmpty(): JSX.Element {
    const { type } = useValues(definitionPopupLogic)
    return (
        <div className="definition-popup-description empty">
            There is no description for this {getSingularType(type)}
        </div>
    )
}

DefinitionPopup.Description = Description
DefinitionPopup.DescriptionEmpty = DescriptionEmpty

export function getSingularType(type: TaxonomicFilterGroupType): string {
    switch (type) {
        case TaxonomicFilterGroupType.Actions:
            return 'action'
        case TaxonomicFilterGroupType.Cohorts:
        case TaxonomicFilterGroupType.CohortsWithAllUsers:
            return 'cohort'
        case TaxonomicFilterGroupType.Elements:
            return 'element'
        case TaxonomicFilterGroupType.Events:
        case TaxonomicFilterGroupType.CustomEvents:
            return 'event'
        case TaxonomicFilterGroupType.EventProperties:
        case TaxonomicFilterGroupType.PersonProperties:
        case TaxonomicFilterGroupType.GroupsPrefix: // Group properties
            return 'property'
        case TaxonomicFilterGroupType.PageviewUrls:
            return 'pageview url'
        case TaxonomicFilterGroupType.Screens:
            return 'screen'
        case TaxonomicFilterGroupType.Wildcards:
            return 'wildcard'
        default:
            return 'definition'
    }
}

function Example({ value }: { value: string }): JSX.Element {
    const { type } = useValues(definitionPopupLogic)
    let data: KeyMapping | null = null

    if (
        // NB: also update "selectedItemHasPopup" below
        type === TaxonomicFilterGroupType.Events ||
        type === TaxonomicFilterGroupType.EventProperties ||
        type === TaxonomicFilterGroupType.PersonProperties ||
        type === TaxonomicFilterGroupType.GroupsPrefix
    ) {
        data = getKeyMapping(value, 'event')
    } else if (type === TaxonomicFilterGroupType.Elements) {
        data = getKeyMapping(value, 'element')
    }

    return data?.examples?.[0] ? (
        <div className="definition-popup-examples">Example: {data?.examples?.join(', ')}</div>
    ) : (
        <></>
    )
}

DefinitionPopup.Example = Example

export { DefinitionPopup }
