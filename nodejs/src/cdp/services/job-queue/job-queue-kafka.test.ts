import { migrateKafkaCyclotronInvocation } from './job-queue-kafka'

describe('CyclotronJobQueue - kafka', () => {
    describe('migrateKafkaCyclotronInvocation', () => {
        // Pulled from a real job in kafka
        const legacyFormat = {
            id: '01971158-5dd2-0000-2dde-9d3478269401',
            globals: {
                event: { event: 'foo' },
            },
            teamId: 1,
            queue: 'hog',
            queuePriority: 0,
            timings: [
                {
                    kind: 'hog',
                    duration_ms: 0.6164590120315552,
                },
            ],
            hogFunctionId: '0196a6b9-1104-0000-f099-9cf11985a307',
            vmState: {
                bytecodes: {},
                stack: [],
                upvalues: [],
            },
            queueParameters: {
                response: {
                    status: 200,
                    headers: {
                        'access-control-allow-origin': '*',
                        'content-type': 'text/plain',
                        date: 'Tue, 27 May 2025 10:45:04 GMT',
                        'content-length': '0',
                    },
                },
                body: '',
                timings: [
                    {
                        kind: 'async_function',
                        duration_ms: 2429.0499999523163,
                    },
                ],
            },
        }

        it('should convert to the current format', () => {
            const invocation = migrateKafkaCyclotronInvocation(legacyFormat as any)

            expect(invocation).toMatchInlineSnapshot(`
                {
                  "functionId": "0196a6b9-1104-0000-f099-9cf11985a307",
                  "id": "01971158-5dd2-0000-2dde-9d3478269401",
                  "queue": "hog",
                  "queueParameters": {
                    "body": "",
                    "response": {
                      "headers": {
                        "access-control-allow-origin": "*",
                        "content-length": "0",
                        "content-type": "text/plain",
                        "date": "Tue, 27 May 2025 10:45:04 GMT",
                      },
                      "status": 200,
                    },
                    "timings": [
                      {
                        "duration_ms": 2429.0499999523163,
                        "kind": "async_function",
                      },
                    ],
                  },
                  "queuePriority": 0,
                  "state": {
                    "globals": {
                      "event": {
                        "event": "foo",
                      },
                    },
                    "timings": [
                      {
                        "duration_ms": 0.6164590120315552,
                        "kind": "hog",
                      },
                    ],
                    "vmState": {
                      "bytecodes": {},
                      "stack": [],
                      "upvalues": [],
                    },
                  },
                  "teamId": 1,
                }
            `)
        })
    })
})
