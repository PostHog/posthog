/*

Tests for a basic CRUD API for destinations supporting GET, POST, PUT, and
DELETE, corresponding to creating, reading, updating, and deleting destinations
as well as other similar operations.

We also have an API for the list of destination types, which provides a list of
types along with the schema for the configuration for each type. This is used
to validate the configuration for each destination.

We do not attempt to handle e.g. idempotency of requests although that may be a
good idea if we hit issues with e.g. retry logic and concurrency. See for
example https://www.mscharhag.com/api-design/rest-making-post-patch-idempotent
for an example way to implement this.

*/

import { describe, test, expect } from '@jest/globals'
import jwt from 'jsonwebtoken'

describe('DestinationType API', () => {
    describe('GET destination types', () => {
        test.concurrent('should be able to retrieve a list of destination types', async () => {
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const destinationTypes = await listDestinationTypesOk(token, projectId)
            expect(destinationTypes).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        type: 'webhook',
                        configSchema: expect.any(Object),
                    }),
                ])
            )
        })

        test.concurrent('project id must be a number', async () => {
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const response = await listDestinationTypes(token, 'invalid')
            expect(response.status).toEqual(400)
        })

        test.concurrent(
            "should not be able to retrieve a list of destination types if you don't have access to the project",
            async () => {
                const projectId = (await createProjectOk()).id
                const token = await generateJwt({ projectIds: [], userId: 1 })
                const response = await listDestinationTypes(token, projectId)
                expect(response.status).toEqual(403)
            }
        )
    })
})

describe('Destination API', () => {
    describe('POST destination', () => {
        test.concurrent('should be able to create a destination', async () => {
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const response = await postDestination(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: {
                    url: 'https://example.com',
                },
            })
            expect(response.status).toEqual(201)
        })

        test.concurrent('should not be able to create a destination with an invalid config schema', async () => {
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const response = await postDestination(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: {
                    invalid: 'config',
                },
            })
            expect(response.status).toEqual(400)
        })

        test.concurrent(
            "should not be able to create a destination if you don't have access to the project",
            async () => {
                const projectId = (await createProjectOk()).id
                const token = await generateJwt({ projectIds: [], userId: 1 })
                const response = await postDestination(token, projectId, {
                    name: 'Test Destination',
                    description: 'Test Description',
                    type: 'webhook',
                    config: {
                        url: 'https://example.com',
                    },
                })
                expect(response.status).toEqual(403)
            }
        )
    })

    describe('GET destination', () => {
        test.concurrent('should be able to retrieve a destination', async () => {
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const destination = await postDestinationOk(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            const retrievedDestination = await getDestinationOk(token, projectId, destinationId)
            expect(retrievedDestination).toEqual(expect.objectContaining(destination))
        })

        test.concurrent('should not be able to retrieve a destination from another project', async () => {
            const projectId = (await createProjectOk()).id
            const otherProjectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId, otherProjectId], userId: 1 })
            const destination = await postDestinationOk(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()

            const response = await getDestination(token, otherProjectId, destinationId)
            expect(response.status).toEqual(404)
        })

        test.concurrent(
            "should not be able to retrieve a destination if you don't have access to the project",
            async () => {
                const projectId = (await createProjectOk()).id
                const token = await generateJwt({ projectIds: [projectId], userId: 1 })
                const destination = await postDestinationOk(token, projectId, {
                    name: 'Test Destination',
                    description: 'Test Description',
                    type: 'webhook',
                    config: { url: 'https://example.com' },
                })
                const destinationId = destination.id
                expect(destinationId).toBeDefined()

                const unauthorizedToken = await generateJwt({ projectIds: [], userId: 1 })
                const response = await getDestination(unauthorizedToken, projectId, destinationId)
                expect(response.status).toEqual(403)
            }
        )
    })

    describe('PUT destination', () => {
        test.concurrent('should be able to update a destination', async () => {
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const destination = await postDestinationOk(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()
            const updatedDestination = await putDestinationOk(token, projectId, destinationId, {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            expect(updatedDestination).toEqual(
                expect.objectContaining({
                    id: destinationId,
                    name: 'Updated Destination',
                    description: 'Updated Description',
                })
            )
        })

        test.concurrent('should not be able to update a destination with an invalid config schema', async () => {
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const destination = await postDestinationOk(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()
            const response = await putDestination(token, projectId, destinationId, {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'webhook',
                config: { invalid: 'config' },
            })
            expect(response.status).toEqual(400)
        })

        test.concurrent('should not be able to change the destination type', async () => {
            // For simplicity of handling e.g. the schema of `config` do not
            // want to allow changing the destination type rather the user
            // should delete and recreate a distination.
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const destination = await postDestinationOk(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()
            const response = await putDestination(token, projectId, destinationId, {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'email',
                config: { url: 'https://example.com' },
            })
            expect(response.status).toEqual(400)
        })

        test.concurrent('should not be able to update a destination with an invalid id', async () => {
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const response = await putDestination(token, projectId, 'invalid', {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            expect(response.status).toEqual(400)
        })

        test.concurrent('should not be able to update a destination from another project', async () => {
            const projectId = (await createProjectOk()).id
            const otherProjectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId, otherProjectId], userId: 1 })
            const destination = await postDestinationOk(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()

            const response = await putDestination(token, otherProjectId, destinationId, {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            expect(response.status).toEqual(404)
        })

        test.concurrent(
            "should not be able to update a destination if you don't have access to the project",
            async () => {
                const projectId = (await createProjectOk()).id
                const token = await generateJwt({ projectIds: [projectId], userId: 1 })
                const destination = await postDestinationOk(token, projectId, {
                    name: 'Test Destination',
                    description: 'Test Description',
                    type: 'webhook',
                    config: { url: 'https://example.com' },
                })
                const destinationId = destination.id
                expect(destinationId).toBeDefined()

                const unauthorizedToken = await generateJwt({ projectIds: [], userId: 1 })
                const response = await putDestination(unauthorizedToken, projectId, destinationId, {
                    name: 'Updated Destination',
                    description: 'Updated Description',
                    type: 'webhook',
                    config: { url: 'https://example.com' },
                })
                expect(response.status).toEqual(403)
            }
        )
    })

    describe('DELETE destination', () => {
        test.concurrent('should be able to delete a destination', async () => {
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const destination = await postDestinationOk(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()

            const response = await deleteDestination(token, projectId, destinationId)
            expect(response.status).toEqual(204)

            // Check that the destination is no longer retrievable
            const getResponse = await getDestination(token, projectId, destinationId)
            expect(getResponse.status).toEqual(404)
        })

        test.concurrent('should not be able to delete a destination with an invalid id', async () => {
            const id = 'invalid'
            const projectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId], userId: 1 })
            const response = await deleteDestination(token, projectId, id)
            expect(response.status).toEqual(400)
        })

        test.concurrent('should not be able to delete a destination from another project', async () => {
            const projectId = (await createProjectOk()).id
            const otherProjectId = (await createProjectOk()).id
            const token = await generateJwt({ projectIds: [projectId, otherProjectId], userId: 1 })
            const destination = await postDestinationOk(token, projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()

            const response = await deleteDestination(token, otherProjectId, destinationId)
            expect(response.status).toEqual(404)

            // Check that the destination is still retrievable
            const getResponse = await getDestination(token, projectId, destinationId)
            expect(getResponse.status).toEqual(200)
        })

        test.concurrent(
            "should not be able to delete a destination if you don't have access to the project",
            async () => {
                const projectId = (await createProjectOk()).id
                const token = await generateJwt({ projectIds: [projectId], userId: 1 })
                const destination = await postDestinationOk(token, projectId, {
                    name: 'Test Destination',
                    description: 'Test Description',
                    type: 'webhook',
                    config: { url: 'https://example.com' },
                })
                const destinationId = destination.id
                expect(destinationId).toBeDefined()

                const unauthorizedToken = await generateJwt({ projectIds: [], userId: 1 })
                const response = await deleteDestination(unauthorizedToken, projectId, destinationId)
                expect(response.status).toEqual(403)

                // Check that the destination is still retrievable
                const getResponse = await getDestination(token, projectId, destinationId)
                expect(getResponse.status).toEqual(200)
            }
        )
    })
})

const listDestinationTypes = async (token: string, projectId: any): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destination-types`, {
        headers: {
            Authorization: `Bearer ${token}`,
        },
    })
}

const listDestinationTypesOk = async (token: string, projectId: number): Promise<DestinationType[]> => {
    const response = await listDestinationTypes(token, projectId)
    if (!response.ok) {
        throw new Error(`Failed to list destination types: ${response.statusText}`)
    }
    return await response.json()
}

const postDestination = async (
    token: string,
    projectId: number,
    destinationData: DestinationCreate
): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destinations`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(destinationData),
    })
}

const postDestinationOk = async (
    token: string,
    projectId: number,
    destinationData: DestinationCreate
): Promise<Destination> => {
    const response = await postDestination(token, projectId, destinationData)
    if (!response.ok) {
        throw new Error(`Failed to create destination: ${response.statusText}`)
    }
    return await response.json()
}

const putDestination = async (
    token: string,
    projectId: number,
    id: string,
    destinationData: DestinationUpdate
): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destinations/${id}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(destinationData),
    })
}

const putDestinationOk = async (
    token: string,
    projectId: number,
    id: string,
    destinationData: DestinationUpdate
): Promise<Destination> => {
    const response = await putDestination(token, projectId, id, destinationData)
    if (!response.ok) {
        throw new Error(`Failed to update destination: ${response.statusText}`)
    }
    return await response.json()
}

const getDestination = async (token: string, projectId: number, id: string): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destinations/${id}`, {
        headers: {
            Authorization: `Bearer ${token}`,
        },
    })
}

const getDestinationOk = async (token: string, projectId: number, id: string): Promise<Destination> => {
    const response = await getDestination(token, projectId, id)
    if (!response.ok) {
        throw new Error(`Failed to retrieve destination: ${response.statusText}`)
    }
    return await response.json()
}

const deleteDestination = async (token: string, projectId: number, id: string): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destinations/${id}`, {
        method: 'DELETE',
        headers: {
            Authorization: `Bearer ${token}`,
        },
    })
}

const createProjectOk = async (): Promise<{ id: number }> => {
    // This isn't really an API method but rather a helper method to create a
    // projectId.
    return { id: Math.floor(Math.random() * 100000) }
}

const generateJwt = async (claims: Record<string, unknown>): Promise<string> => {
    // Generate a token to use for HTTP requests, with the given claims using
    // the jsonwebtoken library. We use the SECRET_KEY environment variable to
    // sign the token.
    const secret = process.env.SECRET_KEY
    if (!secret) {
        throw new Error('Missing SECRET_KEY environment variable')
    }

    return jwt.sign(claims, secret, { algorithm: 'HS256' })
}

type DestinationType = {
    type: string
    name: string
    description: string
    schema: Record<string, unknown> // A JSONSchema describing the configuration
}

type DestinationCreate = {
    name: string // Name displayed to the user
    description: string // Description displayed to the user
    type: string // Type of destination, e.g. webhook, email, Stripe etc.
    config: Record<string, unknown> // Configuration for the destination, e.g. webhook URL, email address, Stripe API key etc.
}

type DestinationUpdate = DestinationCreate

type Destination = DestinationCreate & {
    id: string
    created_at: string // ISO 8601 timestamp
    updated_at: string // ISO 8601 timestamp
}
