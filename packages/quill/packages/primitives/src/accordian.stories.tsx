import type { Meta, StoryObj } from '@storybook/react-vite'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './accordion'

const meta = {
    title: 'Primitives/Accordion',
    component: Accordion,
    tags: ['autodocs'],
} satisfies Meta<typeof Accordion>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Accordion>
            <AccordionItem>
                <AccordionTrigger>Item 1</AccordionTrigger>
                <AccordionContent>Content 1</AccordionContent>
            </AccordionItem>
            <AccordionItem>
                <AccordionTrigger>Item 2</AccordionTrigger>
                <AccordionContent>Content 2</AccordionContent>
            </AccordionItem>
        </Accordion>
    ),
} satisfies Story

export const Multiple: Story = {
    render: () => (
        <Accordion multiple>
            <AccordionItem>
                <AccordionTrigger>Item 1</AccordionTrigger>
                <AccordionContent>Content 1</AccordionContent>
            </AccordionItem>
            <AccordionItem>
                <AccordionTrigger>Item 2</AccordionTrigger>
                <AccordionContent>Content 2</AccordionContent>
            </AccordionItem>
        </Accordion>
    ),
} satisfies Story
