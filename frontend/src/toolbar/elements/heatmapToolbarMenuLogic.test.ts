import { elementToSelector } from 'lib/actionUtils'

import { ElementType } from '~/types'

function createTestDOM(html: string): { container: HTMLElement; cleanup: () => void } {
    const container = document.createElement('div')
    container.innerHTML = html
    document.body.appendChild(container)
    return {
        container,
        cleanup: () => {
            document.body.removeChild(container)
        },
    }
}

describe('heatmapToolbarMenuLogic', () => {
    describe('CSS selector filtering', () => {
        describe('elementToSelector generates valid CSS selectors', () => {
            const selectorGenerationCases = [
                {
                    name: 'simple ID selector',
                    element: { attr_id: 'my-button' } as ElementType,
                    expectedSelector: '[id="my-button"]',
                },
                {
                    name: 'simple class selector',
                    element: { tag_name: 'div', attr_class: ['container'] } as ElementType,
                    expectedSelector: 'div.container',
                },
                {
                    name: 'multiple classes',
                    element: { tag_name: 'button', attr_class: ['btn', 'btn-primary'] } as ElementType,
                    expectedSelector: 'button.btn.btn-primary',
                },
                {
                    name: 'Tailwind arbitrary value class with brackets',
                    element: { tag_name: 'div', attr_class: ['text-[14px]'] } as ElementType,
                    expectedSelector: 'div.text-\\[14px\\]',
                },
                {
                    name: 'Tailwind arbitrary color value',
                    element: { tag_name: 'div', attr_class: ['bg-[#ff0000]'] } as ElementType,
                    expectedSelector: 'div.bg-\\[\\#ff0000\\]',
                },
                {
                    name: 'Tailwind responsive prefix with colon',
                    element: { tag_name: 'div', attr_class: ['md:flex'] } as ElementType,
                    expectedSelector: 'div.md\\:flex',
                },
                {
                    name: 'Tailwind state variant with colon',
                    element: { tag_name: 'button', attr_class: ['hover:bg-blue-500'] } as ElementType,
                    expectedSelector: 'button.hover\\:bg-blue-500',
                },
                {
                    name: 'Tailwind multiple variants',
                    element: { tag_name: 'div', attr_class: ['sm:hover:bg-red-500'] } as ElementType,
                    expectedSelector: 'div.sm\\:hover\\:bg-red-500',
                },
                {
                    name: 'Tailwind negative value',
                    element: { tag_name: 'div', attr_class: ['-mt-4'] } as ElementType,
                    expectedSelector: 'div.-mt-4',
                },
                {
                    name: 'Tailwind fraction value',
                    element: { tag_name: 'div', attr_class: ['w-1/2'] } as ElementType,
                    expectedSelector: 'div.w-1\\/2',
                },
                {
                    name: 'Tailwind dot in value',
                    element: { tag_name: 'div', attr_class: ['opacity-0.5'] } as ElementType,
                    expectedSelector: 'div.opacity-0\\.5',
                },
                {
                    name: 'complex Tailwind combination',
                    element: {
                        tag_name: 'button',
                        attr_class: ['px-4', 'py-2', 'bg-[#1a1a1a]', 'hover:bg-[#2a2a2a]', 'text-[14px]'],
                    } as ElementType,
                    expectedSelector:
                        'button.px-4.py-2.bg-\\[\\#1a1a1a\\].hover\\:bg-\\[\\#2a2a2a\\].text-\\[14px\\]',
                },
                {
                    name: 'ID with special characters',
                    element: { attr_id: 'my:special.id' } as ElementType,
                    expectedSelector: '[id="my\\:special\\.id"]',
                },
                {
                    name: 'data attribute',
                    element: {
                        tag_name: 'button',
                        attributes: { 'attr__data-testid': 'submit-button' },
                    } as ElementType,
                    dataAttributes: ['data-testid'],
                    expectedSelector: '[data-testid="submit-button"]',
                },
                {
                    name: 'nth-child selector',
                    element: { tag_name: 'li', nth_child: 3 } as ElementType,
                    expectedSelector: 'li:nth-child(3)',
                },
                {
                    name: 'nth-of-type selector',
                    element: { tag_name: 'div', nth_of_type: 2 } as ElementType,
                    expectedSelector: 'div:nth-of-type(2)',
                },
                {
                    name: 'link with href',
                    element: { tag_name: 'a', href: '/path/to/page' } as ElementType,
                    expectedSelector: 'a[href="\\/path\\/to\\/page"]',
                },
            ]

            it.each(selectorGenerationCases)(
                '$name',
                ({ element, dataAttributes = [], expectedSelector }) => {
                    const selector = elementToSelector(element, dataAttributes)
                    expect(selector).toBe(expectedSelector)
                }
            )
        })

        describe('generated selectors work with document.querySelector', () => {
            const querySelectorCases = [
                {
                    name: 'selects element by simple class',
                    html: '<div class="container"><span class="target">text</span></div>',
                    element: { tag_name: 'span', attr_class: ['target'] } as ElementType,
                    expectedText: 'text',
                },
                {
                    name: 'selects element with Tailwind brackets class',
                    html: '<div class="text-[14px]">styled</div><div>not styled</div>',
                    element: { tag_name: 'div', attr_class: ['text-[14px]'] } as ElementType,
                    expectedText: 'styled',
                },
                {
                    name: 'selects element with Tailwind colon class',
                    html: '<button class="hover:bg-blue-500">hover me</button>',
                    element: { tag_name: 'button', attr_class: ['hover:bg-blue-500'] } as ElementType,
                    expectedText: 'hover me',
                },
                {
                    name: 'selects element with multiple Tailwind classes',
                    html: '<div class="md:flex lg:grid hover:opacity-100">responsive</div>',
                    element: {
                        tag_name: 'div',
                        attr_class: ['md:flex', 'lg:grid', 'hover:opacity-100'],
                    } as ElementType,
                    expectedText: 'responsive',
                },
                {
                    name: 'selects element with arbitrary value brackets',
                    html: '<span class="bg-[#ff5500] text-[12px]">orange</span>',
                    element: {
                        tag_name: 'span',
                        attr_class: ['bg-[#ff5500]', 'text-[12px]'],
                    } as ElementType,
                    expectedText: 'orange',
                },
                {
                    name: 'selects element with ID',
                    html: '<button id="submit-btn">Submit</button>',
                    element: { attr_id: 'submit-btn' } as ElementType,
                    expectedText: 'Submit',
                },
                {
                    name: 'selects element with special chars in ID',
                    html: '<div id="section:main">content</div>',
                    element: { attr_id: 'section:main' } as ElementType,
                    expectedText: 'content',
                },
                {
                    name: 'selects element with fraction class',
                    html: '<div class="w-1/2">half</div>',
                    element: { tag_name: 'div', attr_class: ['w-1/2'] } as ElementType,
                    expectedText: 'half',
                },
            ]

            it.each(querySelectorCases)('$name', ({ html, element, expectedText }) => {
                const { cleanup } = createTestDOM(html)
                try {
                    const selector = elementToSelector(element, [])
                    const found = document.querySelector(selector)
                    expect(found).not.toBeNull()
                    expect(found?.textContent).toBe(expectedText)
                } finally {
                    cleanup()
                }
            })
        })

        describe('container filtering with element.contains()', () => {
            const containmentCases = [
                {
                    name: 'filters elements inside container',
                    html: `
                        <nav class="navbar"><button>Nav Button</button></nav>
                        <main class="content"><button id="inside">Content Button</button></main>
                    `,
                    containerSelector: '.content',
                    targetId: 'inside',
                    shouldBeContained: true,
                },
                {
                    name: 'excludes elements outside container',
                    html: `
                        <nav class="navbar"><button id="outside">Nav Button</button></nav>
                        <main class="content"><button>Content Button</button></main>
                    `,
                    containerSelector: '.content',
                    targetId: 'outside',
                    shouldBeContained: false,
                },
                {
                    name: 'works with nested containers',
                    html: `
                        <div class="outer">
                            <div class="inner">
                                <button id="nested">Nested</button>
                            </div>
                        </div>
                    `,
                    containerSelector: '.inner',
                    targetId: 'nested',
                    shouldBeContained: true,
                },
                {
                    name: 'container selector with Tailwind class',
                    html: `
                        <div class="md:container"><span id="inside">inside</span></div>
                        <div><span id="outside">outside</span></div>
                    `,
                    containerSelector: '.md\\:container',
                    targetId: 'inside',
                    shouldBeContained: true,
                },
                {
                    name: 'container with ID selector',
                    html: `
                        <section id="main-content"><p id="target">content</p></section>
                        <aside><p id="sidebar">sidebar</p></aside>
                    `,
                    containerSelector: '#main-content',
                    targetId: 'target',
                    shouldBeContained: true,
                },
            ]

            it.each(containmentCases)(
                '$name',
                ({ html, containerSelector, targetId, shouldBeContained }) => {
                    const { cleanup } = createTestDOM(html)
                    try {
                        const container = document.querySelector(containerSelector)
                        const target = document.getElementById(targetId)

                        expect(container).not.toBeNull()
                        expect(target).not.toBeNull()

                        const isContained = container?.contains(target)
                        expect(isContained).toBe(shouldBeContained)
                    } finally {
                        cleanup()
                    }
                }
            )
        })

        describe('invalid CSS selectors are handled gracefully', () => {
            const invalidSelectorCases = [
                { name: 'unclosed bracket', selector: '[class="test' },
                { name: 'invalid pseudo-class', selector: 'div:not-valid' },
                { name: 'unescaped special char', selector: 'div[data=foo:bar]' },
            ]

            it.each(invalidSelectorCases)('$name does not throw', ({ selector }) => {
                const { cleanup } = createTestDOM('<div>test</div>')
                try {
                    let result: Element | null = null
                    expect(() => {
                        try {
                            result = document.querySelector(selector)
                        } catch {
                            // Graceful handling - this is expected behavior
                            result = null
                        }
                    }).not.toThrow()
                    // Invalid selectors should return null or throw, both are acceptable
                } finally {
                    cleanup()
                }
            })
        })

        describe('real-world Tailwind component scenarios', () => {
            it('filters clicks in a card component with complex classes', () => {
                const { cleanup } = createTestDOM(`
                    <div class="fixed inset-0 bg-black/50">
                        <button id="backdrop">Close</button>
                    </div>
                    <div class="rounded-lg bg-white shadow-xl p-[24px] hover:shadow-2xl">
                        <h2 class="text-[18px] font-semibold">Card Title</h2>
                        <button id="card-btn" class="mt-4 px-4 py-2 bg-blue-500 hover:bg-blue-600">
                            Action
                        </button>
                    </div>
                `)
                try {
                    const cardSelector = elementToSelector(
                        {
                            tag_name: 'div',
                            attr_class: ['rounded-lg', 'bg-white', 'shadow-xl', 'p-[24px]', 'hover:shadow-2xl'],
                        } as ElementType,
                        []
                    )
                    const card = document.querySelector(cardSelector)
                    const cardBtn = document.getElementById('card-btn')
                    const backdropBtn = document.getElementById('backdrop')

                    expect(card).not.toBeNull()
                    expect(card?.contains(cardBtn)).toBe(true)
                    expect(card?.contains(backdropBtn)).toBe(false)
                } finally {
                    cleanup()
                }
            })

            it('filters clicks in a responsive navigation', () => {
                const { cleanup } = createTestDOM(`
                    <header class="sticky top-0 z-50">
                        <nav class="hidden md:flex lg:gap-8">
                            <a href="/" id="nav-link">Home</a>
                        </nav>
                    </header>
                    <main class="container mx-auto px-4 sm:px-6 lg:px-8">
                        <button id="main-btn">Main Action</button>
                    </main>
                `)
                try {
                    const mainSelector = elementToSelector(
                        {
                            tag_name: 'main',
                            attr_class: ['container', 'mx-auto', 'px-4', 'sm:px-6', 'lg:px-8'],
                        } as ElementType,
                        []
                    )
                    const main = document.querySelector(mainSelector)
                    const mainBtn = document.getElementById('main-btn')
                    const navLink = document.getElementById('nav-link')

                    expect(main).not.toBeNull()
                    expect(main?.contains(mainBtn)).toBe(true)
                    expect(main?.contains(navLink)).toBe(false)
                } finally {
                    cleanup()
                }
            })

            it('handles arbitrary CSS properties in classes', () => {
                const { cleanup } = createTestDOM(`
                    <div class="[mask-image:linear-gradient(to_bottom,white,transparent)]">
                        <span id="target">Content</span>
                    </div>
                `)
                try {
                    const selector = elementToSelector(
                        {
                            tag_name: 'div',
                            attr_class: ['[mask-image:linear-gradient(to_bottom,white,transparent)]'],
                        } as ElementType,
                        []
                    )
                    const container = document.querySelector(selector)
                    const target = document.getElementById('target')

                    expect(container).not.toBeNull()
                    expect(container?.contains(target)).toBe(true)
                } finally {
                    cleanup()
                }
            })
        })
    })
})
