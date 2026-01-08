import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuSection, LemonSwitch } from '@posthog/lemon-ui'

import { JSONContent } from 'lib/components/RichContentEditor/types'

import { CustomerProfileScope } from '~/types'

import { DEFAULT_PERSON_PROFILE_CONTENT, personProfileLogic } from '../personProfileLogic'

interface CustomerProfileMenuProps {
    scope: CustomerProfileScope
    content: JSONContent[]
}

export function CustomerProfileMenu({ scope, content }: CustomerProfileMenuProps): JSX.Element | null {
    const defaultContent = scope === CustomerProfileScope.PERSON ? DEFAULT_PERSON_PROFILE_CONTENT : []
    const { changed, isProfileConfigEnabled } = useValues(personProfileLogic)
    const { removeNode, addNode, resetToDefaults, saveChanges } = useActions(personProfileLogic)

    const handleChange = (nodeType: string | undefined, checked: boolean): void => {
        if (nodeType === undefined) {
            return
        }
        checked ? addNode(nodeType) : removeNode(nodeType)
    }

    const items: LemonMenuSection[] = [
        {
            title: 'Visible tiles',
            items: defaultContent.map((node) => ({
                label: () => (
                    <LemonSwitch
                        key={node.type}
                        label={node.title || node.type}
                        checked={content.some((c) => c.type === node.type)}
                        onChange={(checked) => handleChange(node?.type, checked)}
                        fullWidth
                    />
                ),
            })),
        },
    ]

    if (!isProfileConfigEnabled) {
        return null
    }

    return (
        <>
            <LemonMenu items={items} closeOnClickInside={false}>
                <LemonButton type="secondary" icon={<IconGear />} children="Edit profile" sideIcon={null} />
            </LemonMenu>
            {changed && (
                <>
                    <LemonButton
                        type="primary"
                        className="ml-2"
                        children="Save changes"
                        sideIcon={null}
                        onClick={() => saveChanges()}
                    />
                    <LemonButton
                        type="secondary"
                        className="ml-2"
                        children="Cancel"
                        sideIcon={null}
                        onClick={() => resetToDefaults()}
                    />
                </>
            )}
        </>
    )
}
