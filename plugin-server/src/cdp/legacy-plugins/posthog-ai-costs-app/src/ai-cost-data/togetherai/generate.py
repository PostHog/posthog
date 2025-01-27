price_brackets = {
    (0, 4): 0.1,  # Up to 4B
    (4.1, 8): 0.2,  # 4.1B - 8B
    (8.1, 21): 0.3,  # 8.1B - 21B
    (21.1, 41): 0.8,  # 21.1B - 41B
    (41.1, 73): 0.9,  # 41B - 70B
}


llama_price_brackets = {
    (6.9, 7.1): 0.2,  # Up to 4B
    (12.9, 13.1): 0.225,  # 4.1B - 8B
    (33.9, 34.1): 0.776,  # 4.1B - 8B
    (69.9, 70.1): 0.9,  # 8.1B - 21B
}


# Model data provided by the user
lang_models = [
    ("zero-one-ai/Yi-34B", 34),
    ("zero-one-ai/Yi-6B", 6),
    ("google/gemma-2b", 2),
    ("google/gemma-7b", 7),
    ("meta-llama/Llama-2-70b-hf", 70),
    ("meta-llama/Llama-2-13b-hf", 13),
    ("meta-llama/Llama-2-7b-hf", 7),
    ("microsoft/phi-2", 2),
    ("Nexusflow/NexusRaven-V2-13B", 13),
    ("Qwen/Qwen1.5-0.5B", 0.5),
    ("Qwen/Qwen1.5-1.8B", 1.8),
    ("Qwen/Qwen1.5-4B", 4),
    ("Qwen/Qwen1.5-7B", 7),
    ("Qwen/Qwen1.5-14B", 14),
    ("Qwen/Qwen1.5-72B", 72),
    ("togethercomputer/GPT-JT-Moderation-6B", 6),
    ("togethercomputer/LLaMA-2-7B-32K", 7),
    ("togethercomputer/RedPajama-INCITE-Base-3B-v1", 3),
    ("togethercomputer/RedPajama-INCITE-7B-Base", 7),
    ("togethercomputer/RedPajama-INCITE-Instruct-3B-v1", 3),
    ("togethercomputer/RedPajama-INCITE-7B-Instruct", 7),
    ("togethercomputer/StripedHyena-Hessian-7B", 7),
    ("mistralai/Mistral-7B-v0.1", 7),
    ("mistralai/Mixtral-8x7B-v0.1", 46.7),
]
chat_models = [
    ("allenai/OLMo-7B-Instruct", 7),
    ("allenai/OLMo-7B-Twin-2T", 7),
    ("allenai/OLMo-7B", 7),
    ("Austism/chronos-hermes-13b", 13),
    ("deepseek-ai/deepseek-coder-33b-instruct", 33),
    ("garage-bAInd/Platypus2-70B-instruct", 70),
    ("google/gemma-2b-it", 2),
    ("google/gemma-7b-it", 7),
    ("Gryphe/MythoMax-L2-13b", 13),
    ("lmsys/vicuna-13b-v1.5", 13),
    ("lmsys/vicuna-7b-v1.5", 7),
    ("codellama/CodeLlama-13b-Instruct-hf", 13),
    ("codellama/CodeLlama-34b-Instruct-hf", 34),
    ("codellama/CodeLlama-70b-Instruct-hf", 70),
    ("codellama/CodeLlama-7b-Instruct-hf", 7),
    ("meta-llama/Llama-2-70b-chat-hf", 70),
    ("meta-llama/Llama-2-13b-chat-hf", 13),
    ("meta-llama/Llama-2-7b-chat-hf", 7),
    ("mistralai/Mistral-7B-Instruct-v0.1", 7),
    ("mistralai/Mistral-7B-Instruct-v0.2", 7),
    ("mistralai/Mixtral-8x7B-Instruct-v0.1", 46.7),
    ("NousResearch/Nous-Capybara-7B-V1p9", 7),
    ("NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO", 46.7),
    ("NousResearch/Nous-Hermes-2-Mixtral-8x7B-SFT", 46.7),
    ("NousResearch/Nous-Hermes-llama-2-7b", 7),
    ("NousResearch/Nous-Hermes-Llama2-13b", 13),
    ("NousResearch/Nous-Hermes-2-Yi-34B", 34),
    ("openchat/openchat-3.5-1210", 7),
    ("Open-Orca/Mistral-7B-OpenOrca", 7),
    ("Qwen/Qwen1.5-0.5B-Chat", 0.5),
    ("Qwen/Qwen1.5-1.8B-Chat", 1.8),
    ("Qwen/Qwen1.5-4B-Chat", 4),
    ("Qwen/Qwen1.5-7B-Chat", 7),
    ("Qwen/Qwen1.5-14B-Chat", 14),
    ("Qwen/Qwen1.5-72B-Chat", 72),
    ("snorkelai/Snorkel-Mistral-PairRM-DPO", 7),
    ("togethercomputer/alpaca-7b", 7),
    ("teknium/OpenHermes-2-Mistral-7B", 7),
    ("teknium/OpenHermes-2p5-Mistral-7B", 7),
    ("togethercomputer/Llama-2-7B-32K-Instruct", 7),
    ("togethercomputer/RedPajama-INCITE-Chat-3B-v1", 3),
    ("togethercomputer/RedPajama-INCITE-7B-Chat", 7),
    ("togethercomputer/StripedHyena-Nous-7B", 7),
    ("Undi95/ReMM-SLERP-L2-13B", 13),
    ("Undi95/Toppy-M-7B", 7),
    ("WizardLM/WizardLM-13B-V1.2", 13),
    ("upstage/SOLAR-10.7B-Instruct-v1.0", 10.7),
]

'''
export const costs: ModelRow[] = [
  {
    model: {
      operator: "equals",
      value: "zero-one-ai/Yi-34B-Chat",
    },
    cost: {
      prompt_token: 0.0000009,
      completion_token: 0.0000009,
    },
  },
];
'''

models = [c for c in lang_models if "llama" not in c[0].lower()]

for model, context_length in models:

    found = False

    for (low, high), cost in price_brackets.items():
        if context_length >= low and context_length <= high:
            print('''
{
    model: {
        operator: "equals",
        value: "'''+model+'''",
    },
    cost: {
        prompt_token: '''+format(cost/1_000_000, '.15f')+''',
        completion_token: '''+format(cost/1_000_000, '.15f')+''',
    },
},
          ''')
            found = True

    if not found:
        # Throw error
        print("Error: ", model, context_length)
        exit(1)
    found = False
