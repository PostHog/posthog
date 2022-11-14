import { useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonModal } from 'lib/components/LemonModal'
import { rolesLogic } from './rolesLogic'

export function CreateRoleModal(): JSX.Element {
    const { createRoleModalShown } = useValues(rolesLogic)
    const handleClose = (): void => {

    }

    const handleSubmit = (): void => {

    }

    return (
        <LemonModal
            onClose={handleClose}
            isOpen={createRoleModalShown}
            title="Create Role"
            footer={
                <LemonButton
                    type="primary"
                    disabled={false}
                    onClick={handleSubmit}
                >
                    Create Role
                </LemonButton>
            }
        >

        </LemonModal>
    )
}
