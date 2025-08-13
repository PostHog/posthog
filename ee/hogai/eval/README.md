# AI evals

We use AI evaluations (evals) to test our AI outputs against a curated set of inputs. Evals allow us to verify prompt performance, spot regressions, or compare different model versions.

![Greg Brockman on evals](https://res.cloudinary.com/dwxrm0iul/image/upload/v1731538464/tweet-1733553161884127435_2_cpectu.png)

We currently use [Braintrust](https://braintrust.dev) as our evaluation platform. Braintrust tracks evaluation results, including LLM traces - which helps both track performance, and dig into any issues on a case-by-case basis. To access Braintrust and/or get an API key for it, ask #team-max-ai.

## Running evals

1. Export environment variable `BRAINTRUST_API_KEY` (ask #team-max-ai).
2. Run all evals with:

    ```bash
    pytest ee/hogai/eval
    ```

    The key bit is specifying the `ee/hogai/eval` directory – that activates our eval-specific config, `ee/hogai/eval/pytest.ini`!

    As always with pytest, you can also run a specific file, e.g. `pytest ee/hogai/eval/eval_root.py`.

3. Voila! Max ran, evals executed, and results and traces uploaded to the Braintrust platform + summarized in the terminal.

For historical eval runs, see the [full Experiments list in Braintrust](https://www.braintrust.dev/app/PostHog/p/Max%20AI/experiments).
