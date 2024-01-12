import './NotebookScene.scss'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, lemonToast } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { base64Encode } from 'lib/utils'
import { getTextFromFile, selectFiles } from 'lib/utils/file-utils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NotebooksTable } from './NotebooksTable/NotebooksTable'

export const scene: SceneExport = {
    component: NotebooksScene,
}

export function NotebooksScene(): JSX.Element {
    return (
        <div className="space-y-4">
            <PageHeader
                buttons={
                    <>
                        <LemonMenu
                            items={[
                                {
                                    label: 'Load from JSON',
                                    onClick: () => {
                                        void selectFiles({
                                            contentType: 'application/json',
                                            multiple: false,
                                        })
                                            .then((files) => getTextFromFile(files[0]))
                                            .then((text) => {
                                                const data = JSON.parse(text)
                                                if (data.type !== 'doc') {
                                                    throw new Error('Not a notebook')
                                                }

                                                // Looks like a notebook
                                                router.actions.push(
                                                    urls.canvas(),
                                                    {},
                                                    {
                                                        '🦔': base64Encode(text),
                                                    }
                                                )
                                            })
                                            .catch((e) => {
                                                lemonToast.error(e.message)
                                            })
                                    },
                                },
                            ]}
                        >
                            <LemonButton icon={<IconEllipsis />} size="small" />
                        </LemonMenu>
                        <LemonButton data-attr="new-notebook" to={urls.notebook('new')} type="primary">
                            New notebook
                        </LemonButton>
                    </>
                }
            />

            <NotebooksTable />
        </div>
    )
}
