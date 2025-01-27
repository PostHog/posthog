const { createEvent, getMeta, resetMeta, clone } = require("@posthog/plugin-scaffold/test/utils");

const { processEvent } = require("./index");

beforeEach(() => {
    // Making sure plugin meta has our custom test config
    resetMeta({
        config: {
            greeting: "Dzień dobry!",
        },
    });
});

test("processEvent adds properties", async () => {
    // Create a random event
    const event0 = createEvent({ event: "$ai_generation", properties: {
        $ai_provider: "openai",
        $ai_model: "gpt-4-turbo-2024-04-09",
        $ai_input_tokens: 100,
        $ai_output_tokens: 200
    }
    });

    // Must clone the event since `processEvent` will mutate it
    const event1 = await processEvent(clone(event0), getMeta());
    expect(event1).toEqual({
        ...event0,
        properties: {
            ...event0.properties,
            $ai_input_cost_usd: 0.001,
            $ai_output_cost_usd: 0.006,
            $ai_total_cost_usd: 0.007
        },
    });

    // Floating point fun
    const event2 = createEvent({ event: "$ai_generation", properties: {
        $ai_provider: "openai",
        $ai_model: "gpt-4o-mini",
        $ai_input_tokens: 25,
        $ai_output_tokens: 100
    }
    });

    // Must clone the event since `processEvent` will mutate it
    const event3 = await processEvent(clone(event2), getMeta());
    expect(event3).toEqual({
        ...event2,
        properties: {
            ...event2.properties,
            $ai_input_cost_usd: 0.00000375,
            $ai_output_cost_usd: 0.00006,
            $ai_total_cost_usd: 0.00006375
        },
    });

});
