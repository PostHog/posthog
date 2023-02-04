import { ComponentMeta } from '@storybook/react'
import { ElementType } from '~/types'
import { EventElements } from './EventElements'

export default {
    title: 'Components/Html Elements',
    component: EventElements,
} as ComponentMeta<typeof EventElements>

export function EmptyDisplay(): JSX.Element {
    return <EventElements elements={[] as ElementType[]} />
}

const elementsExample = [
    {
        text: 'Insights',
        tag_name: 'span',
        attr_class: ['text-default'],
        href: '/insights',
        attr_id: null,
        nth_child: 1,
        nth_of_type: 1,
        attributes: {
            attr__class: 'text-default',
            attr__href: '/insights',
        },
        order: 0,
    },
    {
        text: undefined,
        tag_name: 'span',
        attr_class: ['LemonButton__content', 'flex', 'items-center'],
        href: undefined,
        attr_id: null,
        nth_child: 2,
        nth_of_type: 2,
        attributes: {
            attr__class: 'LemonButton__content flex items-center',
        },
        order: 1,
    },
    {
        text: undefined,
        tag_name: 'a',
        attr_class: [
            'LemonButton',
            'LemonButton--full-width',
            'LemonButton--hasIcon',
            'LemonButton--hasSideIcon',
            'LemonButton--status-stealth',
            'LemonButton--tertiary',
        ],
        href: '/insights',
        attr_id: null,
        nth_child: 1,
        nth_of_type: 1,
        attributes: {
            attr__class:
                'LemonButton LemonButton--tertiary LemonButton--status-stealth LemonButton--full-width LemonButton--hasIcon LemonButton--hasSideIcon',
            'attr__data-attr': 'menu-item-savedinsights',
            attr__href: '/insights',
            attr__type: 'button',
        },
        order: 2,
    },
    {
        text: undefined,
        tag_name: 'div',
        attr_class: ['LemonButtonWithSideAction'],
        href: undefined,
        attr_id: null,
        nth_child: 1,
        nth_of_type: 1,
        attributes: {
            attr__class: 'LemonButtonWithSideAction',
        },
        order: 3,
    },
    {
        text: undefined,
        tag_name: 'li',
        attr_class: undefined,
        href: undefined,
        attr_id: null,
        nth_child: 5,
        nth_of_type: 3,
        attributes: {},
        order: 4,
    },
    {
        text: undefined,
        tag_name: 'ul',
        attr_class: undefined,
        href: undefined,
        attr_id: null,
        nth_child: 1,
        nth_of_type: 1,
        attributes: {},
        order: 5,
    },
    {
        text: undefined,
        tag_name: 'div',
        attr_class: ['SideBar__content'],
        href: undefined,
        attr_id: null,
        nth_child: 1,
        nth_of_type: 1,
        attributes: {
            attr__class: 'SideBar__content',
        },
        order: 6,
    },
    {
        text: undefined,
        tag_name: 'div',
        attr_class: ['SideBar__slider'],
        href: undefined,
        attr_id: null,
        nth_child: 1,
        nth_of_type: 1,
        attributes: {
            attr__class: 'SideBar__slider',
        },
        order: 7,
    },
    {
        text: undefined,
        tag_name: 'div',
        attr_class: ['SideBar', 'SideBar__layout'],
        href: undefined,
        attr_id: null,
        nth_child: 4,
        nth_of_type: 3,
        attributes: {
            attr__class: 'SideBar SideBar__layout',
        },
        order: 8,
    },
    {
        text: undefined,
        tag_name: 'div',
        attr_class: undefined,
        href: undefined,
        attr_id: null,
        nth_child: 1,
        nth_of_type: 1,
        attributes: {},
        order: 9,
    },
    {
        text: undefined,
        tag_name: 'div',
        attr_class: undefined,
        href: undefined,
        attr_id: 'root',
        nth_child: 4,
        nth_of_type: 1,
        attributes: {
            attr__id: 'root',
        },
        order: 10,
    },
    {
        text: undefined,
        tag_name: 'body',
        attr_class: undefined,
        href: undefined,
        attr_id: null,
        nth_child: 2,
        nth_of_type: 1,
        attributes: {},
        order: 11,
    },
] as ElementType[]

export function ReadOnlyDisplay(): JSX.Element {
    return <EventElements elements={elementsExample} />
}

export function WithoutCentralHghlightDisplay(): JSX.Element {
    return <EventElements elements={elementsExample} highlight={false} />
}
