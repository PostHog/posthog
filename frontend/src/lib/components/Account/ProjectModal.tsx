import { useActions, useValues } from 'kea'

import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'

import { newAccountMenuLogic } from './newAccountMenuLogic'
import { ProjectSwitcher } from './ProjectSwitcher'

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
