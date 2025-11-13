from rest_framework import serializers


class MessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant", "system"])
    content = serializers.CharField()


class AnthropicMessagesRequestSerializer(serializers.Serializer):
    model = serializers.CharField(
        required=True, help_text="The model to use for completion (e.g., 'claude-3-5-sonnet-20241022')"
    )
    messages = serializers.ListField(
        child=serializers.DictField(), required=True, help_text="List of message objects with 'role' and 'content'"
    )
    max_tokens = serializers.IntegerField(
        required=False, default=4096, min_value=1, help_text="Maximum number of tokens to generate"
    )
    temperature = serializers.FloatField(
        required=False, min_value=0.0, max_value=1.0, help_text="Sampling temperature between 0 and 1"
    )
    top_p = serializers.FloatField(required=False, min_value=0.0, max_value=1.0, help_text="Nucleus sampling parameter")
    top_k = serializers.IntegerField(required=False, min_value=0, help_text="Top-k sampling parameter")
    stream = serializers.BooleanField(required=False, default=False, help_text="Whether to stream the response")
    stop_sequences = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Custom stop sequences"
    )
    system = serializers.JSONField(required=False, help_text="System prompt (string or array of content blocks)")
    metadata = serializers.JSONField(required=False, help_text="Metadata to attach to the request")
    thinking = serializers.JSONField(required=False, help_text="Thinking configuration for extended thinking")
    tools = serializers.ListField(required=False, help_text="List of tools available to the model")
    tool_choice = serializers.JSONField(required=False, help_text="Controls which tool is called")
    service_tier = serializers.ChoiceField(
        choices=["auto", "standard_only"], required=False, help_text="Service tier for the request"
    )


class AnthropicContentBlockSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["text"])
    text = serializers.CharField()


class AnthropicUsageSerializer(serializers.Serializer):
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    cache_creation_input_tokens = serializers.IntegerField(required=False, allow_null=True)
    cache_read_input_tokens = serializers.IntegerField(required=False, allow_null=True)
    server_tool_use = serializers.JSONField(required=False, allow_null=True)
    service_tier = serializers.ChoiceField(choices=["standard", "priority", "batch"], required=False, allow_null=True)


class AnthropicMessagesResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["message"])
    role = serializers.ChoiceField(choices=["assistant"])
    content = serializers.ListField(child=serializers.DictField())
    model = serializers.CharField()
    stop_reason = serializers.ChoiceField(
        choices=["end_turn", "max_tokens", "stop_sequence", "tool_use", "pause_turn", "refusal"], allow_null=True
    )
    stop_sequence = serializers.CharField(allow_null=True, required=False)
    usage = AnthropicUsageSerializer()


class ChatCompletionMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["system", "user", "assistant", "function", "tool", "developer"])
    content = serializers.CharField(allow_null=True, required=False)
    name = serializers.CharField(required=False)
    function_call = serializers.JSONField(required=False)
    tool_calls = serializers.ListField(required=False)


class ChatCompletionRequestSerializer(serializers.Serializer):
    model = serializers.CharField(
        required=True, help_text="The model to use for completion (e.g., 'gpt-4', 'gpt-3.5-turbo')"
    )
    messages = serializers.ListField(
        child=serializers.DictField(), required=True, help_text="List of message objects with 'role' and 'content'"
    )
    temperature = serializers.FloatField(
        required=False, min_value=0.0, max_value=2.0, help_text="Sampling temperature between 0 and 2"
    )
    top_p = serializers.FloatField(required=False, min_value=0.0, max_value=1.0, help_text="Nucleus sampling parameter")
    n = serializers.IntegerField(required=False, min_value=1, help_text="Number of completions to generate")
    stream = serializers.BooleanField(required=False, default=False, help_text="Whether to stream the response")
    stream_options = serializers.JSONField(required=False, help_text="Additional options for streaming")
    stop = serializers.ListField(child=serializers.CharField(), required=False, help_text="Stop sequences")
    max_tokens = serializers.IntegerField(required=False, min_value=1, help_text="Maximum number of tokens to generate")
    max_completion_tokens = serializers.IntegerField(
        required=False, min_value=1, help_text="Maximum number of completion tokens (alternative to max_tokens)"
    )
    presence_penalty = serializers.FloatField(
        required=False, min_value=-2.0, max_value=2.0, help_text="Presence penalty between -2.0 and 2.0"
    )
    frequency_penalty = serializers.FloatField(
        required=False, min_value=-2.0, max_value=2.0, help_text="Frequency penalty between -2.0 and 2.0"
    )
    logit_bias = serializers.JSONField(required=False, help_text="Logit bias mapping")
    user = serializers.CharField(required=False, help_text="Unique user identifier")
    tools = serializers.ListField(required=False, help_text="List of tools available to the model")
    tool_choice = serializers.JSONField(required=False, help_text="Controls which tool is called")
    parallel_tool_calls = serializers.BooleanField(required=False, help_text="Whether to allow parallel tool calls")
    response_format = serializers.JSONField(required=False, help_text="Format for the model output")
    seed = serializers.IntegerField(required=False, help_text="Random seed for deterministic sampling")
    logprobs = serializers.BooleanField(required=False, help_text="Whether to return log probabilities")
    top_logprobs = serializers.IntegerField(
        required=False, min_value=0, max_value=20, help_text="Number of most likely tokens to return at each position"
    )
    modalities = serializers.ListField(
        child=serializers.ChoiceField(choices=["text", "audio"]), required=False, help_text="Output modalities"
    )
    prediction = serializers.JSONField(required=False, help_text="Prediction content for speculative decoding")
    audio = serializers.JSONField(required=False, help_text="Audio input parameters")
    reasoning_effort = serializers.ChoiceField(
        choices=["none", "minimal", "low", "medium", "high", "default"],
        required=False,
        help_text="Reasoning effort level for o-series models",
    )
    verbosity = serializers.ChoiceField(
        choices=["concise", "standard", "verbose"],
        required=False,
        help_text="Controls the verbosity level of the model's output",
    )
    store = serializers.BooleanField(
        required=False, help_text="Whether to store the output for model distillation or evals"
    )
    web_search_options = serializers.JSONField(required=False, help_text="Web search tool configuration")
    functions = serializers.ListField(
        required=False, help_text="Deprecated in favor of tools. List of functions the model may call"
    )
    function_call = serializers.JSONField(
        required=False, help_text="Deprecated in favor of tool_choice. Controls which function is called"
    )


class ChatCompletionChoiceSerializer(serializers.Serializer):
    index = serializers.IntegerField()
    message = ChatCompletionMessageSerializer()
    finish_reason = serializers.CharField(allow_null=True)


class ChatCompletionUsageSerializer(serializers.Serializer):
    prompt_tokens = serializers.IntegerField()
    completion_tokens = serializers.IntegerField()
    total_tokens = serializers.IntegerField()
    completion_tokens_details = serializers.JSONField(required=False, allow_null=True)
    prompt_tokens_details = serializers.JSONField(required=False, allow_null=True)


class ChatCompletionResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    object = serializers.ChoiceField(choices=["chat.completion"])
    created = serializers.IntegerField()
    model = serializers.CharField()
    choices = serializers.ListField(child=ChatCompletionChoiceSerializer())
    usage = ChatCompletionUsageSerializer(required=False, allow_null=True)
    system_fingerprint = serializers.CharField(required=False, allow_null=True)
    service_tier = serializers.ChoiceField(
        choices=["auto", "default", "flex", "scale", "priority"], required=False, allow_null=True
    )


class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.DictField()
