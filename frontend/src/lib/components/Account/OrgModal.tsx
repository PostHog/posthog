import { useActions, useValues } from 'kea'

import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'

import { OrgSwitcher } from './OrgSwitcher'
import { newAccountMenuLogic } from './newAccountMenuLogic'

export function OrgModal(): JSX.Element {
    const { isOrgSwitcherOpen } = useValues(newAccountMenuLogic)
    const { closeOrgSwitcher } = useActions(newAccountMenuLogic)

    return (
        <DialogPrimitive open={isOrgSwitcherOpen} onOpenChange={(open) => !open && closeOrgSwitcher()}>
            <DialogPrimitiveTitle>Switch organization</DialogPrimitiveTitle>
            <OrgSwitcher />
        </DialogPrimitive>
    )
}
