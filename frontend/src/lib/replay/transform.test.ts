import posthogEE from '@posthog/ee/exports'
import { ifEeDescribe } from 'lib/ee.test'

const heartEyesEmojiURL =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAApgAAAKYB3X3/OAAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAANCSURBVEiJtZZPbBtFFMZ/M7ubXdtdb1xSFyeilBapySVU8h8OoFaooFSqiihIVIpQBKci6KEg9Q6H9kovIHoCIVQJJCKE1ENFjnAgcaSGC6rEnxBwA04Tx43t2FnvDAfjkNibxgHxnWb2e/u992bee7tCa00YFsffekFY+nUzFtjW0LrvjRXrCDIAaPLlW0nHL0SsZtVoaF98mLrx3pdhOqLtYPHChahZcYYO7KvPFxvRl5XPp1sN3adWiD1ZAqD6XYK1b/dvE5IWryTt2udLFedwc1+9kLp+vbbpoDh+6TklxBeAi9TL0taeWpdmZzQDry0AcO+jQ12RyohqqoYoo8RDwJrU+qXkjWtfi8Xxt58BdQuwQs9qC/afLwCw8tnQbqYAPsgxE1S6F3EAIXux2oQFKm0ihMsOF71dHYx+f3NND68ghCu1YIoePPQN1pGRABkJ6Bus96CutRZMydTl+TvuiRW1m3n0eDl0vRPcEysqdXn+jsQPsrHMquGeXEaY4Yk4wxWcY5V/9scqOMOVUFthatyTy8QyqwZ+kDURKoMWxNKr2EeqVKcTNOajqKoBgOE28U4tdQl5p5bwCw7BWquaZSzAPlwjlithJtp3pTImSqQRrb2Z8PHGigD4RZuNX6JYj6wj7O4TFLbCO/Mn/m8R+h6rYSUb3ekokRY6f/YukArN979jcW+V/S8g0eT/N3VN3kTqWbQ428m9/8k0P/1aIhF36PccEl6EhOcAUCrXKZXXWS3XKd2vc/TRBG9O5ELC17MmWubD2nKhUKZa26Ba2+D3P+4/MNCFwg59oWVeYhkzgN/JDR8deKBoD7Y+ljEjGZ0sosXVTvbc6RHirr2reNy1OXd6pJsQ+gqjk8VWFYmHrwBzW/n+uMPFiRwHB2I7ih8ciHFxIkd/3Omk5tCDV1t+2nNu5sxxpDFNx+huNhVT3/zMDz8usXC3ddaHBj1GHj/As08fwTS7Kt1HBTmyN29vdwAw+/wbwLVOJ3uAD1wi/dUH7Qei66PfyuRj4Ik9is+hglfbkbfR3cnZm7chlUWLdwmprtCohX4HUtlOcQjLYCu+fzGJH2QRKvP3UNz8bWk1qMxjGTOMThZ3kvgLI5AzFfo379UAAAAASUVORK5CYII='

describe('replay/transform', () => {
    ifEeDescribe('transform', () => {
        test('text is wrapped in a div to apply styling', () => {
            const helloWorld = posthogEE.mobileReplay?.transformToWeb([
                {
                    data: { screen: 'App Home Page', width: 300, height: 600 },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 10,
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
                                    color: 'red',
                                    backgroundColor: 'yellow',
                                    borderWidth: '4px',
                                    borderColor: 'blue',
                                    borderRadius: '10px',
                                },
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(helloWorld).toMatchSnapshot()
        })

        test('can ignore unknown types', () => {
            expect(
                posthogEE.mobileReplay?.transformToWeb([
                    {
                        data: { width: 300, height: 600 },
                        timestamp: 1,
                        type: 4,
                    },
                    { type: 9999 },
                ])
            ).toStrictEqual([{ type: 4, data: { href: '', width: 300, height: 600 }, timestamp: 1 }])
        })

        test('can ignore unknown wireframe types', () => {
            const unexpectedWireframeType = posthogEE.mobileReplay?.transformToWeb([
                {
                    data: { screen: 'App Home Page', width: 300, height: 600 },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 10,
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

        test('can convert images', () => {
            const exampleWithImage = posthogEE.mobileReplay?.transformToWeb([
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
                    type: 10,
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
                                    color: 'red',
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
            const exampleWithRectAndText = posthogEE.mobileReplay?.transformToWeb([
                {
                    data: {
                        width: 300,
                        height: 600,
                    },
                    timestamp: 1,
                    type: 4,
                },
                {
                    type: 10,
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
                                    color: 'red',
                                    borderColor: 'blue',
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
                                // clip: {
                                //   bottom: 83,
                                //   right: 44,
                                // },
                                type: 'text',
                                text: 'i am in the box',
                            },
                        ],
                    },
                    timestamp: 1,
                },
            ])
            expect(exampleWithRectAndText).toMatchSnapshot()
        })
    })
})
