#!/usr/bin/env node

// Mock Jest for non-test environment - must be global
;(global as any).jest = {
    fn: () => {
        const mockFn: any = (...args: any[]) => {
            mockFn.mock.calls.push(args)
            return mockFn.mockReturnValue ? mockFn.mockReturnValue() : undefined
        }
        mockFn.mock = { calls: [] as any[][] }
        mockFn.mockResolvedValue = (value: any) => {
            mockFn.mockReturnValue = () => Promise.resolve(value)
            return mockFn
        }
        mockFn.mockReturnValue = (value: any) => {
            mockFn.mockReturnValue = () => value
            return mockFn
        }
        return mockFn
    },
    spyOn: (obj: any, method: string) => {
        const original = obj[method]
        const mockFn: any = (global as any).jest.fn()
        obj[method] = mockFn
        mockFn.mockRestore = () => {
            obj[method] = original
        }
        return mockFn
    },
    useRealTimers: () => {},
}

import cors from 'cors'
import express from 'express'
import inquirer from 'inquirer'

import { NATIVE_HOG_FUNCTIONS } from './index'
import { DestinationTester } from './test/test-helpers'

const PORT = 4321

async function main() {
    const { hogFunction: hogFunctionId } = await inquirer.prompt([
        {
            type: 'list',
            name: 'hogFunction',
            message: 'Select a hog function:',
            choices: NATIVE_HOG_FUNCTIONS.filter((hogFunction) => hogFunction.id !== 'native-dev-center').map(
                (hogFunction) => ({
                    name: hogFunction.name,
                    value: hogFunction.id,
                })
            ),
        },
    ])

    const hogFunction = NATIVE_HOG_FUNCTIONS.find((hogFunction) => hogFunction.id === hogFunctionId)

    if (!hogFunction) {
        throw new Error('You must select a destination. Exiting...')
    }

    const app = express()

    // Enable CORS for localhost
    app.use(
        cors({
            origin: [
                'http://localhost:8000',
                'http://localhost:8010',
                'https://us.posthog.com',
                'https://eu.posthog.com',
            ],
        })
    )

    app.use(express.json())

    app.get('/local-hog-function', (req, res) => {
        res.status(200).json(hogFunction)
    })

    app.post('/local-hog-function/invoke', async (req, res) => {
        const { globals, configuration } = req.body
        const tester = new DestinationTester(hogFunction)

        const convertInputs = (inputs: Record<string, any>): Record<string, any> => {
            return Object.entries(inputs).reduce((acc, [key, value]) => {
                if (value.value !== undefined) {
                    return { ...acc, [key]: value.value }
                }

                if (value.type === 'object') {
                    return { ...acc, [key]: convertInputs(value.value) }
                }

                return acc
            }, {})
        }

        const inputs = convertInputs(configuration.inputs)

        const result = await tester.invoke(globals, inputs)

        res.json({
            result: result,
            status: 'success',
            errors: [],
            logs: result.logs,
        })
    })

    app.listen(PORT, () => {
        console.log(`Server running on port ${PORT}`)
        console.log(
            `You can test your destination by going to https://us.posthog.com/pipeline/new/destination/hog-native-dev-center`
        )
    })
}

main().catch(console.error)
