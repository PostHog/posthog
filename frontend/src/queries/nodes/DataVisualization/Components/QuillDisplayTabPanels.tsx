import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@posthog/quill'

import type { DisplayTabPanelsProps } from './DisplayTabPanels'

export function QuillDisplayTabPanels({ panels, defaultOpenKeys }: DisplayTabPanelsProps): JSX.Element {
    return (
        <Accordion multiple defaultValue={defaultOpenKeys} className="px-3">
            {panels.map((panel) => (
                <AccordionItem key={panel.key} value={panel.key}>
                    <AccordionTrigger>{panel.header}</AccordionTrigger>
                    <AccordionContent>
                        <div className="flex flex-col gap-3 pb-2">{panel.content}</div>
                    </AccordionContent>
                </AccordionItem>
            ))}
        </Accordion>
    )
}
