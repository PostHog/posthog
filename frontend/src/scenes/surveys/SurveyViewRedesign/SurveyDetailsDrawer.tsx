import { ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import {
    Button,
    Drawer,
    DrawerClose,
    DrawerContent,
    DrawerDescription,
    DrawerHeader,
    DrawerTitle,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    useDirection,
} from '@posthog/quill'

import { QuillSurveyDetailsPanel } from './QuillSurveyDetailsPanel'
import { QuillSurveyExportPanel } from './QuillSurveyExportPanel'

export type SurveyDetailsDrawerTab = 'details' | 'export'

type SurveyDetailsDrawerProps = {
    open: boolean
    tab: SurveyDetailsDrawerTab
    showExport: boolean
    surveyName: string
    onTabChange: (tab: SurveyDetailsDrawerTab) => void
    onClose: () => void
}

/**
 * The menu row opens the drawer while its menu closes, so the row that had focus is gone by the time the drawer
 * closes. Focus goes to the scene's "More actions" button instead, which is where the person opened the drawer from.
 */
function sceneMenuTrigger(): HTMLElement | true {
    return document.querySelector<HTMLElement>('[data-attr="scene-menu-bar-trigger"]') ?? true
}

/**
 * The scroller sits inside the tab panel rather than on it. The edge fade is a scroll-driven animation that never
 * finishes, and Base UI waits for a panel's animations to finish before it hides that panel, so a fade on the panel
 * itself leaves the previous tab on screen.
 */
function DrawerScrollBody({ children }: { children: ReactNode }): JSX.Element {
    return <div className="absolute inset-0 overflow-y-auto scroll-mask-y-4 scroll-py-4 p-4">{children}</div>
}

export function SurveyDetailsDrawer({
    open,
    tab,
    showExport,
    surveyName,
    onTabChange,
    onClose,
}: SurveyDetailsDrawerProps): JSX.Element {
    const direction = useDirection()

    return (
        <Drawer
            open={open}
            onOpenChange={(nextOpen) => {
                if (!nextOpen) {
                    onClose()
                }
            }}
            swipeDirection={direction === 'rtl' ? 'left' : 'right'}
        >
            <DrawerContent finalFocus={sceneMenuTrigger} data-attr="survey-details-drawer">
                <div className="flex h-[calc(100dvh-1rem)] min-h-0 flex-col">
                    <DrawerHeader className="flex-row items-start gap-2">
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <DrawerTitle>Survey details</DrawerTitle>
                            <DrawerDescription className="truncate">{surveyName}</DrawerDescription>
                        </div>
                        <DrawerClose
                            render={
                                <Button
                                    size="icon"
                                    aria-label="Close"
                                    tooltip="Close"
                                    data-attr="survey-details-drawer-close"
                                />
                            }
                        >
                            <IconX />
                        </DrawerClose>
                    </DrawerHeader>
                    {showExport ? (
                        <Tabs
                            value={tab}
                            onValueChange={(value) => onTabChange(value as SurveyDetailsDrawerTab)}
                            className="flex min-h-0 flex-1 flex-col"
                        >
                            <TabsList variant="line" className="mx-4 shrink-0">
                                <TabsTrigger value="details" data-attr="survey-details-drawer-tab-details">
                                    Details
                                </TabsTrigger>
                                <TabsTrigger value="export" data-attr="survey-details-drawer-tab-export">
                                    Export
                                </TabsTrigger>
                            </TabsList>
                            <TabsContent value="details" className="relative min-h-0">
                                <DrawerScrollBody>
                                    <QuillSurveyDetailsPanel />
                                </DrawerScrollBody>
                            </TabsContent>
                            <TabsContent value="export" className="relative min-h-0">
                                <DrawerScrollBody>
                                    <QuillSurveyExportPanel />
                                </DrawerScrollBody>
                            </TabsContent>
                        </Tabs>
                    ) : (
                        <div className="relative min-h-0 flex-1">
                            <DrawerScrollBody>
                                <QuillSurveyDetailsPanel />
                            </DrawerScrollBody>
                        </div>
                    )}
                </div>
            </DrawerContent>
        </Drawer>
    )
}
