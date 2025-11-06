import { Message } from 'node-rdkafka'

import { ok } from '../pipelines/results'
import { createParseHeadersStep } from './parse-headers'

describe('createParseHeadersStep', () => {
    let step: ReturnType<typeof createParseHeadersStep>

    beforeEach(() => {
        step = createParseHeadersStep()
    })

    it('should parse headers and return success with headers', async () => {
        const input = {
            message: {
                headers: [{ token: Buffer.from('test-token') }, { distinct_id: Buffer.from('test-user') }],
            } as Pick<Message, 'headers'>,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    token: 'test-token',
                    distinct_id: 'test-user',
                    force_disable_person_processing: false,
                },
            })
        )
    })

    it('should preserve additional input properties', async () => {
        const input = {
            message: {
                headers: [{ token: Buffer.from('test-token') }],
            } as Pick<Message, 'headers'>,
            customField: 'custom-value',
            anotherField: 42,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    token: 'test-token',
                    force_disable_person_processing: false,
                },
            })
        )
    })

    it('should handle empty headers', async () => {
        const input = {
            message: {
                headers: [],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    force_disable_person_processing: false,
                },
            })
        )
    })

    it('should handle undefined headers', async () => {
        const input = {
            message: {
                headers: undefined,
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    force_disable_person_processing: false,
                },
            })
        )
    })

    it('should handle headers with duplicate keys (last value wins)', async () => {
        const input = {
            message: {
                headers: [
                    { token: Buffer.from('first-token') },
                    { distinct_id: Buffer.from('first-user') },
                    { token: Buffer.from('second-token') }, // This should overwrite the first token
                    { distinct_id: Buffer.from('second-user') }, // This should overwrite the first distinct_id
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    token: 'second-token',
                    distinct_id: 'second-user',
                    force_disable_person_processing: false,
                },
            })
        )
    })

    it('should handle complex headers with multiple supported fields', async () => {
        const input = {
            message: {
                headers: [
                    { token: Buffer.from('complex-token') },
                    { distinct_id: Buffer.from('complex-user') },
                    { timestamp: Buffer.from('2023-01-01T00:00:00Z') },
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    token: 'complex-token',
                    distinct_id: 'complex-user',
                    timestamp: '2023-01-01T00:00:00Z',
                    force_disable_person_processing: false,
                },
            })
        )
    })

    it('should handle jwt header', async () => {
        const input = {
            message: {
                headers: [
                    { token: Buffer.from('test-token') },
                    { jwt: Buffer.from('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test') },
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    token: 'test-token',
                    jwt: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test',
                    force_disable_person_processing: false,
                },
            })
        )
    })

    it('should handle string values in headers', async () => {
        const input = {
            message: {
                headers: [
                    { token: 'string-token' },
                    { distinct_id: 'string-user' },
                    { timestamp: '2023-01-01T00:00:00Z' },
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    token: 'string-token',
                    distinct_id: 'string-user',
                    timestamp: '2023-01-01T00:00:00Z',
                    force_disable_person_processing: false,
                },
            })
        )
    })

    it('should handle mixed Buffer and string values in headers', async () => {
        const input = {
            message: {
                headers: [
                    { token: Buffer.from('buffer-token') },
                    { distinct_id: 'string-user' },
                    { timestamp: Buffer.from('2023-01-01T00:00:00Z') },
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    token: 'buffer-token',
                    distinct_id: 'string-user',
                    timestamp: '2023-01-01T00:00:00Z',
                    force_disable_person_processing: false,
                },
            })
        )
    })

    it('should ignore unsupported headers and only parse supported ones', async () => {
        const input = {
            message: {
                headers: [
                    { token: Buffer.from('test-token') },
                    { distinct_id: Buffer.from('test-user') },
                    { unsupported_header: Buffer.from('should-be-ignored') },
                    { ip: Buffer.from('192.168.1.1') },
                    { site_url: Buffer.from('https://example.com') },
                    { custom_field: Buffer.from('custom-value') },
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: {
                    token: 'test-token',
                    distinct_id: 'test-user',
                    force_disable_person_processing: false,
                },
            })
        )
    })

    describe('force_disable_person_processing header', () => {
        it('should parse force_disable_person_processing as true when value is "true"', async () => {
            const input = {
                message: {
                    headers: [{ force_disable_person_processing: Buffer.from('true') }],
                } as Pick<Message, 'headers'>,
            }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    headers: {
                        force_disable_person_processing: true,
                    },
                })
            )
        })

        it('should parse force_disable_person_processing as false when value is "false"', async () => {
            const input = {
                message: {
                    headers: [{ force_disable_person_processing: Buffer.from('false') }],
                } as Pick<Message, 'headers'>,
            }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    headers: {
                        force_disable_person_processing: false,
                    },
                })
            )
        })

        it('should parse force_disable_person_processing as false when value is not "true"', async () => {
            const input = {
                message: {
                    headers: [{ force_disable_person_processing: Buffer.from('1') }],
                } as Pick<Message, 'headers'>,
            }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    headers: {
                        force_disable_person_processing: false,
                    },
                })
            )
        })

        it('should parse force_disable_person_processing as false when header is missing', async () => {
            const input = {
                message: {
                    headers: [{ token: Buffer.from('test-token') }],
                } as Pick<Message, 'headers'>,
            }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    headers: {
                        token: 'test-token',
                        force_disable_person_processing: false,
                    },
                })
            )
        })

        it('should handle force_disable_person_processing with string values', async () => {
            const input = {
                message: {
                    headers: [{ force_disable_person_processing: 'true' }],
                } as Pick<Message, 'headers'>,
            }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    headers: {
                        force_disable_person_processing: true,
                    },
                })
            )
        })

        it('should handle force_disable_person_processing with string "false"', async () => {
            const input = {
                message: {
                    headers: [{ force_disable_person_processing: 'false' }],
                } as Pick<Message, 'headers'>,
            }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    headers: {
                        force_disable_person_processing: false,
                    },
                })
            )
        })

        it('should handle multiple headers including force_disable_person_processing', async () => {
            const input = {
                message: {
                    headers: [
                        { token: Buffer.from('test-token') },
                        { distinct_id: Buffer.from('test-user') },
                        { force_disable_person_processing: Buffer.from('true') },
                    ],
                } as Pick<Message, 'headers'>,
            }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    headers: {
                        token: 'test-token',
                        distinct_id: 'test-user',
                        force_disable_person_processing: true,
                    },
                })
            )
        })
    })
})
