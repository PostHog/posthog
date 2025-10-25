import posthogEE from '@posthog/ee/exports'
import { EventType } from '@posthog/rrweb-types'

import { ifEeDescribe } from 'lib/ee.test'

import { PostHogEE } from '../../../frontend/@posthog/ee/types'
import * as incrementalSnapshotJson from './__mocks__/increment-with-child-duplication.json'
import { validateAgainstWebSchema, validateFromMobile } from './index'
import { wireframe } from './mobile.types'
import { stripBarsFromWireframes } from './transformer/transformers'

const unspecifiedBase64ImageURL =
    'iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAApgAAAKYB3X3/OAAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAANCSURBVEiJtZZPbBtFFMZ/M7ubXdtdb1xSFyeilBapySVU8h8OoFaooFSqiihIVIpQBKci6KEg9Q6H9kovIHoCIVQJJCKE1ENFjnAgcaSGC6rEnxBwA04Tx43t2FnvDAfjkNibxgHxnWb2e/u992bee7tCa00YFsffekFY+nUzFtjW0LrvjRXrCDIAaPLlW0nHL0SsZtVoaF98mLrx3pdhOqLtYPHChahZcYYO7KvPFxvRl5XPp1sN3adWiD1ZAqD6XYK1b/dvE5IWryTt2udLFedwc1+9kLp+vbbpoDh+6TklxBeAi9TL0taeWpdmZzQDry0AcO+jQ12RyohqqoYoo8RDwJrU+qXkjWtfi8Xxt58BdQuwQs9qC/afLwCw8tnQbqYAPsgxE1S6F3EAIXux2oQFKm0ihMsOF71dHYx+f3NND68ghCu1YIoePPQN1pGRABkJ6Bus96CutRZMydTl+TvuiRW1m3n0eDl0vRPcEysqdXn+jsQPsrHMquGeXEaY4Yk4wxWcY5V/9scqOMOVUFthatyTy8QyqwZ+kDURKoMWxNKr2EeqVKcTNOajqKoBgOE28U4tdQl5p5bwCw7BWquaZSzAPlwjlithJtp3pTImSqQRrb2Z8PHGigD4RZuNX6JYj6wj7O4TFLbCO/Mn/m8R+h6rYSUb3ekokRY6f/YukArN979jcW+V/S8g0eT/N3VN3kTqWbQ428m9/8k0P/1aIhF36PccEl6EhOcAUCrXKZXXWS3XKd2vc/TRBG9O5ELC17MmWubD2nKhUKZa26Ba2+D3P+4/MNCFwg59oWVeYhkzgN/JDR8deKBoD7Y+ljEjGZ0sosXVTvbc6RHirr2reNy1OXd6pJsQ+gqjk8VWFYmHrwBzW/n+uMPFiRwHB2I7ih8ciHFxIkd/3Omk5tCDV1t+2nNu5sxxpDFNx+huNhVT3/zMDz8usXC3ddaHBj1GHj/As08fwTS7Kt1HBTmyN29vdwAw+/wbwLVOJ3uAD1wi/dUH7Qei66PfyuRj4Ik9is+hglfbkbfR3cnZm7chlUWLdwmprtCohX4HUtlOcQjLYCu+fzGJH2QRKvP3UNz8bWk1qMxjGTOMThZ3kvgLI5AzFfo379UAAAAASUVORK5CYII='

const heartEyesEmojiURL = 'data:image/png;base64,' + unspecifiedBase64ImageURL

function fakeWireframe(type: string, children?: wireframe[]): wireframe {
    // this is a fake so we can force the type
    return { type, childWireframes: children || [] } as Partial<wireframe> as wireframe
}

describe('replay/transform', () => {
    describe('validation', () => {
        test('example of validating incoming _invalid_ data', () => {
            const invalidData = {
                foo: 'abc',
                bar: 'abc',
            }

            expect(validateFromMobile(invalidData).isValid).toBe(false)
        })

        test('example of validating mobile meta event', () => {
            const validData = {
                data: { width: 1, height: 1 },
                timestamp: 1,
                type: EventType.Meta,
            }

            expect(validateFromMobile(validData)).toStrictEqual({
                isValid: true,
                errors: null,
            })
        })

        describe('validate web schema', () => {
            test('does not block when invalid', () => {
                expect(validateAgainstWebSchema({})).toBeFalsy()
            })

            test('should be valid when...', () => {
                expect(validateAgainstWebSchema({ data: {}, timestamp: 12345, type: 0 })).toBeTruthy()
            })
        })
    })

    ifEeDescribe('transform', () => {
        let posthogEEModule: PostHogEE
        beforeEach(async () => {
            posthogEEModule = await posthogEE()
        })

        test('can process top level screenshot', () => {
            expect(
                posthogEEModule.mobileReplay?.transformToWeb([
                    {
                        data: { width: 300, height: 600 },
                        timestamp: 1,
                        type: 4,
                    },
                    {
                        windowId: '5173a13e-abac-4def-b227-2f81dc2808b6',
                        data: {
                            wireframes: [
                                {
                                    base64: 'image-content',
                                    height: 914,
                                    id: 151700670,
                                    style: {
                                        backgroundColor: '#F3EFF7',
                                    },
                                    type: 'screenshot',
                                    width: 411,
                                    x: 0,
                                    y: 0,
                                },
                            ],
                        },
                        timestamp: 1714397321578,
                        type: 2,
                    },
                ])
            ).toMatchSnapshot()
        })

        test('can process screenshot mutation', () => {
            expect(
                posthogEEModule.mobileReplay?.transformToWeb([
                    {
                        data: { width: 300, height: 600 },
                        timestamp: 1,
                        type: 4,
                    },
                    {
                        windowId: '5173a13e-abac-4def-b227-2f81dc2808b6',
                        data: {
                            source: 0,
                            updates: [
                                {
                                    wireframe: {
                                        base64: 'mutated-image-content',
                                        height: 914,
                                        id: 151700670,
                                        style: {
                                            backgroundColor: '#F3EFF7',
                                        },
                                        type: 'screenshot',
                                        width: 411,
                                        x: 0,
                                        y: 0,
                                    },
                                },
                            ],
                        },
                        timestamp: 1714397336836,
                        type: 3,
                        seen: 3551987272322930,
                    },
                ])
            ).toMatchSnapshot()
        })

        test('can process unknown types without error', () => {
            expect(
                posthogEEModule.mobileReplay?.transformToWeb([
                    {
                        data: { width: 300, height: 600 },
                        timestamp: 1,
                        type: 4,
                    },
                    {
                        data: { href: 'included when present', width: 300, height: 600 },
                        timestamp: 1,
                        type: 4,
                    },
                    { type: 9999 },
                    {
                        type: 2,
                        data: {
                            wireframes: [
                                {
                                    id: 12345,
                                    x: 25,
                                    y: 42,
                                    width: 100,
                                    height: 30,
                                    type: 'image',
                                },
                            ],
                        },
                        timestamp: 1,
                    },
                ])
            ).toMatchSnapshot()
        })

        test('can ignore unknown wireframe types', () => {
            const unexpectedWireframeType = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    data: { screen: 'App Home Page', width: 300, height: 600 },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 2,
                    data: {
                        wireframes: [
                            {
                                id: 12345,
                                x: 11,
                                y: 12,
                                width: 100,
                                height: 30,
                                type: 'something in the SDK but not yet the transformer',
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(unexpectedWireframeType).toMatchSnapshot()
        })

        test('can short-circuit non-mobile full snapshot', () => {
            const allWeb = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    data: { href: 'https://my-awesome.site', width: 300, height: 600 },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 2,
                    data: {
                        node: { the: 'payload' },
                    },
                    timestamp: 1,
                },
            ])
            expect(allWeb).toMatchSnapshot()
        })

        test('can convert images', () => {
            const exampleWithImage = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    data: {
                        screen: 'App Home Page',
                        width: 300,
                        height: 600,
                    },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 2,
                    data: {
                        wireframes: [
                            {
                                id: 12345,
                                x: 11,
                                y: 12,
                                width: 100,
                                height: 30,
                                // clip: {
                                //   bottom: 83,
                                //   right: 44,
                                // },
                                type: 'text',
                                text: 'Ⱏ遲䩞㡛쓯잘ጫ䵤㥦鷁끞鈅毅┌빯湌Თ',
                                style: {
                                    // family: '疴ꖻ䖭㋑⁃⻋ꑧٹ㧕Ⓖ',
                                    // size: 4220431756569966319,
                                    color: '#ffffff',
                                },
                            },
                            {
                                id: 12345,
                                x: 25,
                                y: 42,
                                width: 100,
                                height: 30,
                                // clip: {
                                //   bottom: 83,
                                //   right: 44,
                                // },
                                type: 'image',
                                base64: heartEyesEmojiURL,
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(exampleWithImage).toMatchSnapshot()
        })

        test('can convert rect with text', () => {
            const exampleWithRectAndText = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    data: {
                        width: 300,
                        height: 600,
                    },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 2,
                    data: {
                        wireframes: [
                            {
                                id: 12345,
                                x: 11,
                                y: 12,
                                width: 100,
                                height: 30,
                                type: 'rectangle',
                                style: {
                                    color: '#ee3ee4',
                                    borderColor: '#ee3ee4',
                                    borderWidth: '4',
                                    borderRadius: '10px',
                                },
                            },
                            {
                                id: 12345,
                                x: 13,
                                y: 17,
                                width: 100,
                                height: 30,
                                verticalAlign: 'top',
                                horizontalAlign: 'right',
                                type: 'text',
                                text: 'i am in the box',
                                fontSize: '12px',
                                fontFamily: 'sans-serif',
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(exampleWithRectAndText).toMatchSnapshot()
        })

        test('child wireframes are processed', () => {
            const textEvent = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    data: { screen: 'App Home Page', width: 300, height: 600 },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 2,
                    data: {
                        wireframes: [
                            {
                                id: 123456789,
                                childWireframes: [
                                    {
                                        id: 98765,
                                        childWireframes: [
                                            {
                                                id: 12345,
                                                x: 11,
                                                y: 12,
                                                width: 100,
                                                height: 30,
                                                type: 'text',
                                                text: 'first nested',
                                                style: {
                                                    color: '#ffffff',
                                                    backgroundColor: '#000000',
                                                    borderWidth: '4px',
                                                    borderColor: '#000ddd',
                                                    borderRadius: '10px',
                                                },
                                            },
                                            {
                                                id: 12345,
                                                x: 11,
                                                y: 12,
                                                width: 100,
                                                height: 30,
                                                type: 'text',
                                                text: 'second nested',
                                                style: {
                                                    color: '#ffffff',
                                                    backgroundColor: '#000000',
                                                    borderWidth: '4px',
                                                    borderColor: '#000ddd',
                                                    borderRadius: '10px',
                                                },
                                            },
                                        ],
                                    },
                                    {
                                        id: 12345,
                                        x: 11,
                                        y: 12,
                                        width: 100,
                                        height: 30,
                                        // clip: {
                                        //   bottom: 83,
                                        //   right: 44,
                                        // },
                                        type: 'text',
                                        text: 'third (different level) nested',
                                        style: {
                                            // family: '疴ꖻ䖭㋑⁃⻋ꑧٹ㧕Ⓖ',
                                            // size: 4220431756569966319,
                                            color: '#ffffff',
                                            backgroundColor: '#000000',
                                            borderWidth: '4px',
                                            borderColor: '#000ddd',
                                            borderRadius: '10', // you can omit the pixels
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(textEvent).toMatchSnapshot()
        })

        test('respect incremental ids, replace with body otherwise', () => {
            const textEvent = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    windowId: 'ddc9c89d-2272-4b07-a280-c00db3a9182f',
                    data: {
                        id: 0, // must be an element id - replace with body
                        pointerType: 2,
                        source: 2,
                        type: 7,
                        x: 523,
                        y: 683,
                    },
                    timestamp: 1701355473313,
                    type: 3,
                    delay: 2160,
                },
                {
                    windowId: 'ddc9c89d-2272-4b07-a280-c00db3a9182f',
                    data: {
                        id: 145, // element provided - respected without validation
                        pointerType: 2,
                        source: 2,
                        type: 7,
                        x: 523,
                        y: 683,
                    },
                    timestamp: 1701355473313,
                    type: 3,
                    delay: 2160,
                },
            ])
            expect(textEvent).toMatchSnapshot()
        })

        test('incremental mutations de-duplicate the tree', () => {
            const conversion = posthogEEModule.mobileReplay?.transformEventToWeb(incrementalSnapshotJson)
            expect(conversion).toMatchSnapshot()
        })

        test('omitting x and y is equivalent to setting them to 0', () => {
            expect(
                posthogEEModule.mobileReplay?.transformToWeb([
                    {
                        type: 2,
                        data: {
                            wireframes: [
                                {
                                    id: 12345,
                                    width: 100,
                                    height: 30,
                                    type: 'image',
                                },
                            ],
                        },
                        timestamp: 1,
                    },
                ])
            ).toMatchSnapshot()
        })

        test('can convert status bar', () => {
            const converted = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    data: {
                        width: 300,
                        height: 600,
                    },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 2,
                    data: {
                        wireframes: [
                            {
                                id: 12345,
                                type: 'status_bar',
                                // _we'll process the x and y, but they should always be 0
                                x: 0,
                                y: 0,
                                // we'll process the width
                                // width: 100,
                                height: 30,
                                style: {
                                    // we can't expect to receive all of these values,
                                    // but we'll handle them, because that's easier than not doing
                                    color: '#ee3ee4',
                                    borderColor: '#ee3ee4',
                                    borderWidth: '4',
                                    borderRadius: '10px',
                                    backgroundColor: '#000000',
                                },
                            },
                            {
                                id: 12345,
                                type: 'status_bar',
                                x: 13,
                                y: 17,
                                width: 100,
                                // zero height is respected
                                height: 0,
                                // as with styling we don't expect to receive these values,
                                // but we'll respect them if they are present
                                horizontalAlign: 'right',
                                verticalAlign: 'top',
                                fontSize: '12px',
                                fontFamily: 'sans-serif',
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(converted).toMatchSnapshot()
        })

        test('can convert navigation bar', () => {
            const converted = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    data: {
                        width: 300,
                        height: 600,
                    },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 2,
                    data: {
                        wireframes: [
                            {
                                id: 12345,
                                type: 'navigation_bar',
                                // we respect x and y but expect this to be at the bottom of the screen
                                x: 11,
                                y: 12,
                                // we respect width but expect it to be fullscreen
                                width: 100,
                                height: 30,
                                // as with status bar, we don't expect to receive all of these values,
                                // but we'll respect them if they are present
                                style: {
                                    color: '#ee3ee4',
                                    borderColor: '#ee3ee4',
                                    borderWidth: '4',
                                    borderRadius: '10px',
                                },
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(converted).toMatchSnapshot()
        })

        test('can convert invalid text wireframe', () => {
            const converted = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    data: {
                        width: 300,
                        height: 600,
                    },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 2,
                    data: {
                        wireframes: [
                            {
                                id: 12345,
                                type: 'text',
                                x: 11,
                                y: 12,
                                width: 100,
                                height: 30,
                                style: {
                                    color: '#ee3ee4',
                                    borderColor: '#ee3ee4',
                                    borderWidth: '4',
                                    borderRadius: '10px',
                                },
                                // text property is missing
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(converted).toMatchSnapshot()
        })

        test('can set background image to base64 png', () => {
            const converted = posthogEEModule.mobileReplay?.transformToWeb([
                {
                    data: {
                        width: 300,
                        height: 600,
                    },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 2,
                    data: {
                        wireframes: [
                            {
                                id: 12345,
                                type: 'div',
                                x: 0,
                                y: 0,
                                height: 30,
                                style: { backgroundImage: heartEyesEmojiURL },
                            },
                            {
                                id: 12346,
                                type: 'div',
                                x: 0,
                                y: 0,
                                height: 30,
                                style: { backgroundImage: unspecifiedBase64ImageURL },
                            },
                            {
                                id: 12346,
                                type: 'div',
                                x: 0,
                                y: 0,
                                height: 30,
                                style: { backgroundImage: unspecifiedBase64ImageURL, backgroundSize: 'cover' },
                            },
                            {
                                id: 12346,
                                type: 'div',
                                x: 0,
                                y: 0,
                                height: 30,
                                // should be ignored
                                style: { backgroundImage: null },
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(converted).toMatchSnapshot()
        })

        describe('inputs', () => {
            test('input gets 0 padding by default but can be overridden', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        type: 2,
                        data: {
                            wireframes: [
                                {
                                    id: 12359,
                                    width: 100,
                                    height: 30,
                                    type: 'input',
                                    inputType: 'text',
                                },
                                {
                                    id: 12361,
                                    width: 100,
                                    height: 30,
                                    type: 'input',
                                    inputType: 'text',
                                    style: {
                                        paddingLeft: '16px',
                                        paddingRight: 16,
                                    },
                                },
                            ],
                        },
                        timestamp: 1,
                    })
                ).toMatchSnapshot()
            })

            test('buttons with nested elements', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        type: 2,
                        data: {
                            wireframes: [
                                {
                                    id: 12359,
                                    width: 100,
                                    height: 30,
                                    type: 'input',
                                    inputType: 'button',
                                    childNodes: [
                                        {
                                            id: 12360,
                                            width: 100,
                                            height: 30,
                                            type: 'text',
                                            text: 'click me',
                                        },
                                    ],
                                },
                                {
                                    id: 12361,
                                    width: 100,
                                    height: 30,
                                    type: 'input',
                                    inputType: 'button',
                                    value: 'click me',
                                    childNodes: [
                                        {
                                            id: 12362,
                                            width: 100,
                                            height: 30,
                                            type: 'text',
                                            text: 'and have more text',
                                        },
                                    ],
                                },
                            ],
                        },
                        timestamp: 1,
                    })
                ).toMatchSnapshot()
            })
            test('wrapping with labels', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        type: 2,
                        data: {
                            wireframes: [
                                {
                                    id: 12359,
                                    width: 100,
                                    height: 30,
                                    type: 'input',
                                    inputType: 'checkbox',
                                    label: 'i will wrap the checkbox',
                                },
                            ],
                        },
                        timestamp: 1,
                    })
                ).toMatchSnapshot()
            })

            test('web_view with URL', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        type: 2,
                        data: {
                            wireframes: [
                                {
                                    id: 12365,
                                    width: 100,
                                    height: 30,
                                    type: 'web_view',
                                    url: 'https://example.com',
                                },
                            ],
                        },
                        timestamp: 1,
                    })
                ).toMatchSnapshot()
            })

            test('progress rating', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        type: 2,
                        data: {
                            wireframes: [
                                {
                                    id: 12365,
                                    width: 100,
                                    height: 30,
                                    type: 'input',
                                    inputType: 'progress',
                                    style: { bar: 'rating' },
                                    max: '12',
                                    value: '6.5',
                                },
                            ],
                        },
                        timestamp: 1,
                    })
                ).toMatchSnapshot()
            })

            test('open keyboard custom event', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        timestamp: 1,
                        type: EventType.Custom,
                        data: { tag: 'keyboard', payload: { open: true, height: 150 } },
                    })
                ).toMatchSnapshot()
            })

            test('isolated add mutation', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        timestamp: 1,
                        type: EventType.IncrementalSnapshot,
                        data: {
                            source: 0,
                            adds: [
                                {
                                    parentId: 54321,
                                    wireframe: {
                                        id: 12365,
                                        width: 100,
                                        height: 30,
                                        type: 'input',
                                        inputType: 'progress',
                                        style: { bar: 'rating' },
                                        max: '12',
                                        value: '6.5',
                                    },
                                },
                            ],
                        },
                    })
                ).toMatchSnapshot()
            })

            test('isolated remove mutation', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        timestamp: 1,
                        type: EventType.IncrementalSnapshot,
                        data: {
                            source: 0,
                            removes: [{ parentId: 54321, id: 12345 }],
                        },
                    })
                ).toMatchSnapshot()
            })

            test('isolated update mutation', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        timestamp: 1,
                        type: EventType.IncrementalSnapshot,
                        data: {
                            source: 0,
                            texts: [],
                            attributes: [],
                            updates: [
                                {
                                    parentId: 54321,
                                    wireframe: {
                                        id: 12365,
                                        width: 100,
                                        height: 30,
                                        type: 'input',
                                        inputType: 'progress',
                                        style: { bar: 'rating' },
                                        max: '12',
                                        value: '6.5',
                                    },
                                },
                            ],
                        },
                    })
                ).toMatchSnapshot()
            })

            test('closed keyboard custom event', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        timestamp: 1,
                        type: EventType.Custom,
                        data: { tag: 'keyboard', payload: { open: false } },
                    })
                ).toMatchSnapshot()
            })

            test('radio_group', () => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        type: 2,
                        data: {
                            wireframes: [
                                {
                                    id: 54321,
                                    width: 100,
                                    height: 30,
                                    type: 'radio_group',
                                    timestamp: 12345,
                                    childNodes: [
                                        {
                                            id: 12345,
                                            width: 100,
                                            height: 30,
                                            type: 'input',
                                            inputType: 'radio',
                                            checked: true,
                                            label: 'first',
                                        },
                                        {
                                            id: 12346,
                                            width: 100,
                                            height: 30,
                                            type: 'input',
                                            inputType: 'radio',
                                            checked: false,
                                            label: 'second',
                                        },
                                        {
                                            id: 12347,
                                            width: 100,
                                            height: 30,
                                            type: 'text',
                                            text: 'to check that only radios are given a name',
                                        },
                                    ],
                                },
                            ],
                        },
                        timestamp: 1,
                    })
                ).toMatchSnapshot()
            })
            test.each([
                {
                    id: 12346,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'text',
                    value: 'hello',
                },
                {
                    id: 12347,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'text',
                    // without value
                },
                {
                    id: 12348,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'password',
                    // without value
                },
                {
                    id: 12349,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'email',
                    // without value
                },
                {
                    id: 12350,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'number',
                    // without value
                },
                {
                    id: 12351,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'search',
                    // without value
                },
                {
                    id: 12352,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'tel',
                    disabled: true,
                },
                {
                    id: 12352,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'url',
                    value: 'https://example.io',
                    disabled: false,
                },
                {
                    id: 123123,
                    width: 100,
                    height: 30,
                    type: 'radio_group',
                    // oh, oh, no child nodes
                },
                {
                    id: 12354,
                    width: 100,
                    height: 30,
                    type: 'radio group',
                    childNodes: [
                        {
                            id: 12355,
                            width: 100,
                            height: 30,
                            type: 'input',
                            inputType: 'radio',
                            checked: true,
                            label: 'first',
                        },
                        {
                            id: 12356,
                            width: 100,
                            height: 30,
                            type: 'input',
                            inputType: 'radio',
                            checked: false,
                            label: 'second',
                        },
                    ],
                },
                {
                    id: 12357,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'checkbox',
                    checked: true,
                    label: 'first',
                },
                {
                    id: 12357,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'checkbox',
                    checked: false,
                    label: 'second',
                },
                {
                    id: 12357,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'checkbox',
                    checked: true,
                    disabled: true,
                    label: 'third',
                },
                {
                    id: 12357,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'checkbox',
                    checked: true,
                    disabled: false,
                    // no label
                },
                {
                    id: 12357,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'toggle',
                    checked: true,
                    label: 'first',
                },
                {
                    id: 12357,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'toggle',
                    checked: false,
                    label: 'second',
                },
                {
                    id: 12357,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'toggle',
                    checked: true,
                    disabled: true,
                    label: 'third',
                },
                {
                    id: 12357,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'toggle',
                    checked: true,
                    disabled: false,
                    // no label
                },
                {
                    id: 12358,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'button',
                    value: 'click me',
                },
                {
                    id: 12363,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'textArea',
                    value: 'hello',
                },
                {
                    id: 12364,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'textArea',
                },
                {
                    id: 12365,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'select',
                    value: 'hello',
                    options: ['hello', 'world'],
                },
                {
                    id: 12365,
                    width: 100,
                    height: 30,
                    type: 'input',
                    // missing input type - should be ignored
                    // inputType: 'select',
                    value: 'hello',
                    options: ['hello', 'world'],
                },
                {
                    id: 12365,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'progress',
                    style: { bar: 'circular' },
                },
                {
                    id: 12365,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'progress',
                    style: { bar: 'horizontal' },
                },
                {
                    id: 12365,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'progress',
                    style: { bar: 'horizontal' },
                    value: 0.75,
                },
                {
                    id: 12365,
                    width: 100,
                    height: 30,
                    type: 'input',
                    inputType: 'progress',
                    style: { bar: 'horizontal' },
                    value: 0.75,
                    max: 2.5,
                },
                {
                    id: 12365,
                    width: 100,
                    height: 30,
                    type: 'placeholder',
                    label: 'hello',
                },
                {
                    id: 12365,
                    width: 100,
                    height: 30,
                    type: 'web_view',
                },
            ])('$type - $inputType - $value', (testCase) => {
                expect(
                    posthogEEModule.mobileReplay?.transformEventToWeb({
                        type: 2,
                        data: {
                            wireframes: [testCase],
                        },
                        timestamp: 1,
                    })
                ).toMatchSnapshot()
            })
        })
    })

    describe('separate status and navbar from other wireframes', () => {
        it('no-op', () => {
            expect(stripBarsFromWireframes([])).toEqual({
                appNodes: [],
                statusBar: undefined,
                navigationBar: undefined,
            })
        })

        it('top-level status-bar', () => {
            const statusBar = fakeWireframe('status_bar')
            expect(stripBarsFromWireframes([statusBar])).toEqual({ appNodes: [], statusBar, navigationBar: undefined })
        })

        it('top-level nav-bar', () => {
            const navBar = fakeWireframe('navigation_bar')
            expect(stripBarsFromWireframes([navBar])).toEqual({
                appNodes: [],
                statusBar: undefined,
                navigationBar: navBar,
            })
        })

        it('nested nav-bar', () => {
            const navBar = fakeWireframe('navigation_bar')
            const sourceWithNavBar = [
                fakeWireframe('div', [fakeWireframe('div'), fakeWireframe('div', [navBar, fakeWireframe('div')])]),
            ]
            expect(stripBarsFromWireframes(sourceWithNavBar)).toEqual({
                appNodes: [fakeWireframe('div', [fakeWireframe('div'), fakeWireframe('div', [fakeWireframe('div')])])],
                statusBar: undefined,
                navigationBar: navBar,
            })
        })
    })
})
