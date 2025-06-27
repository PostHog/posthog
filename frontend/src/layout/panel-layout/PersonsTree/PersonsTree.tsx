import { IconUser } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { IconWrapper } from 'lib/ui/IconWrapper/IconWrapper'
import { useEffect, useRef } from 'react'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { personsTreeLogic } from './personsTreeLogic'

export function PersonsTree({ mainRef }: { mainRef: React.RefObject<HTMLElement> }): JSX.Element {
    const { setPanelTreeRef } = useActions(panelLayoutLogic)
    const { personsResults } = useValues(personsTreeLogic)
    const treeRef = useRef<LemonTreeRef>(null)

    useEffect(() => {
        setPanelTreeRef(treeRef)
    }, [treeRef, setPanelTreeRef])

    const treeData: TreeDataItem[] =
        personsResults?.map((person) => ({
            icon: (
                <IconWrapper>
                    <IconUser />
                </IconWrapper>
            ),
            id: person.result_id || '',
            name: String(person.extra_fields?.name || ''),
        })) ?? []

    return (
        <PanelLayoutPanel searchPlaceholder="Search TODO">
            <LemonTree ref={treeRef} contentRef={mainRef} className="px-0 py-1" data={treeData} />
        </PanelLayoutPanel>
    )
}
