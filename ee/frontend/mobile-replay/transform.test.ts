import posthogEE from '@posthog/ee/exports'
import { EventType } from '@rrweb/types'
import { ifEeDescribe } from 'lib/ee.test'

import { PostHogEE } from '../../../frontend/@posthog/ee/types'
import { validateAgainstWebSchema, validateFromMobile } from './index'

const heartEyesEmojiURL =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAApgAAAKYB3X3/OAAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAANCSURBVEiJtZZPbBtFFMZ/M7ubXdtdb1xSFyeilBapySVU8h8OoFaooFSqiihIVIpQBKci6KEg9Q6H9kovIHoCIVQJJCKE1ENFjnAgcaSGC6rEnxBwA04Tx43t2FnvDAfjkNibxgHxnWb2e/u992bee7tCa00YFsffekFY+nUzFtjW0LrvjRXrCDIAaPLlW0nHL0SsZtVoaF98mLrx3pdhOqLtYPHChahZcYYO7KvPFxvRl5XPp1sN3adWiD1ZAqD6XYK1b/dvE5IWryTt2udLFedwc1+9kLp+vbbpoDh+6TklxBeAi9TL0taeWpdmZzQDry0AcO+jQ12RyohqqoYoo8RDwJrU+qXkjWtfi8Xxt58BdQuwQs9qC/afLwCw8tnQbqYAPsgxE1S6F3EAIXux2oQFKm0ihMsOF71dHYx+f3NND68ghCu1YIoePPQN1pGRABkJ6Bus96CutRZMydTl+TvuiRW1m3n0eDl0vRPcEysqdXn+jsQPsrHMquGeXEaY4Yk4wxWcY5V/9scqOMOVUFthatyTy8QyqwZ+kDURKoMWxNKr2EeqVKcTNOajqKoBgOE28U4tdQl5p5bwCw7BWquaZSzAPlwjlithJtp3pTImSqQRrb2Z8PHGigD4RZuNX6JYj6wj7O4TFLbCO/Mn/m8R+h6rYSUb3ekokRY6f/YukArN979jcW+V/S8g0eT/N3VN3kTqWbQ428m9/8k0P/1aIhF36PccEl6EhOcAUCrXKZXXWS3XKd2vc/TRBG9O5ELC17MmWubD2nKhUKZa26Ba2+D3P+4/MNCFwg59oWVeYhkzgN/JDR8deKBoD7Y+ljEjGZ0sosXVTvbc6RHirr2reNy1OXd6pJsQ+gqjk8VWFYmHrwBzW/n+uMPFiRwHB2I7ih8ciHFxIkd/3Omk5tCDV1t+2nNu5sxxpDFNx+huNhVT3/zMDz8usXC3ddaHBj1GHj/As08fwTS7Kt1HBTmyN29vdwAw+/wbwLVOJ3uAD1wi/dUH7Qei66PfyuRj4Ik9is+hglfbkbfR3cnZm7chlUWLdwmprtCohX4HUtlOcQjLYCu+fzGJH2QRKvP3UNz8bWk1qMxjGTOMThZ3kvgLI5AzFfo379UAAAAASUVORK5CYII='

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
    })
})
