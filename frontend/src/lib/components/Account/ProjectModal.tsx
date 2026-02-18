import { useActions, useValues } from 'kea'

import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'

import { ProjectSwitcher } from './ProjectSwitcher'
import { newAccountMenuLogic } from './newAccountMenuLogic'

export function ProjectModal(): JSX.Element {
    const { isProjectSwitcherOpen } = useValues(newAccountMenuLogic)
    const { closeProjectSwitcher } = useActions(newAccountMenuLogic)

    return (
        <DialogPrimitive open={isProjectSwitcherOpen} onOpenChange={(open) => !open && closeProjectSwitcher()}>
            <DialogPrimitiveTitle>Switch project</DialogPrimitiveTitle>
            <ProjectSwitcher />
        </DialogPrimitive>
    )
}
