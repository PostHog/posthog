import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { PathCleaningFilter } from '~/types'

import { RestrictionScope, useRestrictedArea } from '../RestrictedArea'
import { PathRegexModal } from './PathRegexModal'

type PathCleanFilterAddItemButtonProps = {
    onAdd: (filter: PathCleaningFilter) => void
}

export function PathCleanFilterAddItemButton({ onAdd }: PathCleanFilterAddItemButtonProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const quillSurface = useQuillSurface()

    return (
        <>
            <PathRegexModal
                isOpen={visible}
                onClose={() => setVisible(false)}
                onSave={(filter: PathCleaningFilter) => {
                    onAdd(filter)
                    setVisible(false)
                }}
            />

            {quillSurface ? (
                <Button variant="outline" onClick={() => setVisible(true)} disabledReason={restrictedReason}>
                    <IconPlus />
                    Add rule
                </Button>
            ) : (
                <LemonButton
                    onClick={() => setVisible(true)}
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    sideIcon={null}
                    disabledReason={restrictedReason}
                >
                    Add rule
                </LemonButton>
            )}
        </>
    )
}
