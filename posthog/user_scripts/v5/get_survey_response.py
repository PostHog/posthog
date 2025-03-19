#!/usr/bin/env python3
import sys
import json
import traceback

if __name__ == '__main__':
    try:
        for line in sys.stdin:
            value = json.loads(line)
            first_arg = int(value['argument_1'])
            second_arg = int(value['argument_2'])
            result = {'result_name': first_arg + second_arg}
            print(json.dumps(result), end='\n')
            sys.stdout.flush()
    except Exception as e:
        # Log error to stderr
        print(f"Error: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)  # Exit with non-zero code on error
